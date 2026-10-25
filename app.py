
import os
import io
import re
import time
import base64
import zipfile
from urllib.parse import quote_plus

import requests
import streamlit as st
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from sarvamai import SarvamAI

load_dotenv()

st.set_page_config(
    page_title="Samjho | Documents made clear",
    page_icon="📄",
    layout="wide",
)

st.title("📄 Samjho")
st.subheader("Government documents, explained in your language")
st.write(
    "Upload a notice, discover useful sources, and get a practical "
    "explanation you can read or listen to."
)

api_key = os.getenv("SARVAM_API_KEY")
if not api_key:
    st.error("SARVAM_API_KEY is missing from your .env file.")
    st.stop()

client = SarvamAI(api_subscription_key=api_key)

LANGUAGES = {
    "Hindi": "hi-IN",
    "English": "en-IN",
    "Bengali": "bn-IN",
    "Tamil": "ta-IN",
    "Marathi": "mr-IN",
}

# ---------- Lightweight web research ----------

def search_web(query, limit=4):
    """Try DuckDuckGo HTML search. Return an empty list on failure."""
    try:
        response = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0 SamjhoPrototype/1.0"},
            timeout=7,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        results = []

        for item in soup.select(".result"):
            link = item.select_one(".result__a")
            snippet = item.select_one(".result__snippet")
            if not link:
                continue

            url = link.get("href", "")
            title = link.get_text(" ", strip=True)
            description = (
                snippet.get_text(" ", strip=True) if snippet else ""
            )

            if url.startswith("http") and title:
                results.append({
                    "title": title,
                    "url": url,
                    "snippet": description,
                })
            if len(results) >= limit:
                break

        return results
    except Exception:
        return []


def research_sources(document_text):
    # A short query avoids sending an entire document to a search engine.
    keywords = re.sub(r"\s+", " ", document_text[:700]).strip()
    keywords = keywords[:350]

    official = search_web(
        f'site:gov.in OR site:nic.in "{keywords}"',
        limit=4,
    )
    community = search_web(
        f'site:reddit.com {keywords}',
        limit=3,
    )

    return official, community


def format_sources(sources, label):
    if not sources:
        return f"{label}: No search results were retrieved."
    lines = [f"{label}:"]
    for source in sources:
        lines.append(
            f"- {source['title']}\n"
            f"  URL: {source['url']}\n"
            f"  Snippet: {source['snippet']}"
        )
    return "\n".join(lines)


# ---------- Document OCR ----------

def extract_document(uploaded_file, language_code):
    mime_types = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }
    extension = "." + uploaded_file.name.rsplit(".", 1)[-1].lower()
    mime_type = mime_types.get(extension)

    if not mime_type:
        raise ValueError("Unsupported file format.")

    job = client.doc_ai.digitise(
        file=[(uploaded_file.name, uploaded_file, mime_type)],
        language=language_code,
        output_format="md",
    )

    terminal_states = {
        "completed", "partially_completed", "failed", "rejected"
    }
    deadline = time.monotonic() + 180

    while time.monotonic() < deadline:
        status = client.doc_ai.get_status(job_id=job.job_id)
        state = status.status.lower()

        if state in terminal_states:
            break

        time.sleep(4)
    else:
        raise TimeoutError(
            "Document processing took too long. Try again with a smaller file."
        )

    if state not in {"completed", "partially_completed"}:
        raise RuntimeError(f"Document processing ended with status: {state}")

    download = client.doc_ai.get_download_url(job_id=job.job_id)
    archive_response = requests.get(download.url, timeout=30)
    archive_response.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(archive_response.content)) as archive:
        markdown_files = [
            name for name in archive.namelist()
            if name.lower().endswith(".md")
            and "/metadata/" not in name.lower()
            and not name.lower().startswith("metadata/")
        ]

        extracted = "\n\n".join(
            archive.read(name).decode("utf-8", errors="replace")
            for name in markdown_files
        )

    if not extracted.strip():
        raise RuntimeError("No readable text was found in this document.")

    return extracted


# ---------- Interface ----------

left, right = st.columns(2)

with left:
    input_language = st.selectbox(
        "Document language",
        list(LANGUAGES.keys()),
        index=0,
    )

with right:
    output_language = st.selectbox(
        "Explain in",
        ["Hindi", "English", "Bengali", "Tamil", "Marathi"],
        index=0,
    )

uploaded = st.file_uploader(
    "Upload a government notice or circular",
    type=["pdf", "png", "jpg", "jpeg"],
    help="For this demo, use a clear document of 1–3 pages.",
)

voice_file = st.file_uploader(
    "Optional: ask a question by voice (30 seconds max)",
    type=["wav", "mp3", "m4a", "mp4", "ogg", "webm", "flac"],
)

if st.button("Explain my document", type="primary"):
    if not uploaded:
        st.warning("Please upload a document first.")
    elif uploaded.size > 15 * 1024 * 1024:
        st.error("Please use a file smaller than 15 MB.")
    else:
        spoken_question = ""

        try:
            if voice_file:
                with st.spinner("Transcribing your question with Saaras..."):
                    transcription = client.speech_to_text.transcribe(
                        file=voice_file,
                        model="saaras:v4",
                        mode="transcribe",
                    )
                    spoken_question = getattr(
                        transcription, "transcript", ""
                    ) or ""
                if spoken_question:
                    st.info(f"Your question: {spoken_question}")

            with st.spinner("Reading your document with Sarvam Document AI..."):
                document_text = extract_document(
                    uploaded, LANGUAGES[input_language]
                )

            st.session_state["document_text"] = document_text

            with st.expander("View extracted document text"):
                st.text(document_text[:15000])

            with st.spinner("Searching for relevant public sources..."):
                official, community = research_sources(document_text)

            st.session_state["official_sources"] = official
            st.session_state["community_sources"] = community

            official_text = format_sources(official, "OFFICIAL SEARCH RESULTS")
            community_text = format_sources(
                community, "PUBLIC REDDIT SEARCH RESULTS"
            )

            prompt = f"""
You are Samjho, a careful Indian government-document assistant.

Explain the document in {output_language} using simple, accessible language.

DOCUMENT TEXT:
{document_text[:18000]}

{official_text}

{community_text}

USER'S SPOKEN QUESTION:
{spoken_question or "No follow-up question supplied."}

Produce these sections:
1. What this document means.
2. Eligibility and who should pay attention.
3. Deadlines and required documents.
4. A numbered, practical action checklist.
5. What the user should verify with the relevant authority.
6. Questions the user can ask next.

Rules:
- Never invent dates, eligibility conditions, fees, URLs, or requirements.
- Clearly distinguish the uploaded document from external sources.
- Treat official search results as leads; do not claim they are verified
  unless their content directly supports the claim.
- Treat Reddit posts as personal anecdotes, not official rules or
  representative evidence. Never fabricate user experiences.
- If search results are empty or insufficient, say so.
- If sources conflict, explain the conflict and recommend checking
  the responsible official authority.
- Do not guarantee eligibility, approval, or legal outcomes.
"""

            with st.spinner("Generating your action plan with Sarvam-105B..."):
                completion = client.chat.completions(
                    model="sarvam-105b",
                    messages=[{"role": "user", "content": prompt}],
                )
                answer = completion.choices[0].message.content

            if not answer:
                raise RuntimeError("The model returned an empty answer.")

            st.session_state["answer"] = answer

        except Exception as exc:
            st.error(
                f"Could not complete this step: {type(exc).__name__}: {exc}"
            )


# ---------- Display saved results ----------

if st.session_state.get("answer"):
    st.divider()
    st.header("Your action plan")
    st.markdown(st.session_state["answer"])

    official = st.session_state.get("official_sources", [])
    community = st.session_state.get("community_sources", [])

    with st.expander("Official-source search results"):
        if official:
            for source in official:
                st.markdown(f"- [{source['title']}]({source['url']})")
                if source["snippet"]:
                    st.caption(source["snippet"])
        else:
            st.warning(
                "No official results were retrieved. Search the relevant "
                "government portal directly before relying on the advice."
            )

    with st.expander("Public experiences (Reddit search results)"):
        if community:
            st.caption(
                "These are public search results and personal experiences, "
                "not official guidance or verified facts."
            )
            for source in community:
                st.markdown(f"- [{source['title']}]({source['url']})")
                if source["snippet"]:
                    st.caption(source["snippet"])
        else:
            st.info("No Reddit results were retrieved for this document.")

    st.divider()
    st.subheader("Listen to the explanation")

    if st.button("Generate spoken explanation"):
        speech_text = st.session_state["answer"][:2200]
        language_code = LANGUAGES[output_language]

        speakers = {
            "Hindi": "aparna_hi_customer",
            "English": "simran_en_customer",
            "Bengali": None,
            "Tamil": None,
            "Marathi": None,
        }
        speaker = speakers[output_language]

        try:
            if not speaker:
                st.warning(
                    "Choose Hindi or English for this prototype's voice "
                    "output. Additional language-specific voice IDs can "
                    "be added from Sarvam's voice catalogue."
                )
            else:
                with st.spinner("Generating speech with Bulbul..."):
                    audio_response = client.text_to_speech.convert(
                        text=speech_text,
                        model="bulbul:v4-flash",
                        language_code=language_code,
                        speaker=speaker,
                        output_audio_codec="wav",
                    )

                audio_bytes = base64.b64decode(
                    "".join(audio_response.audios)
                )
                st.audio(audio_bytes, format="audio/wav")

        except Exception as exc:
            st.error(
                f"Speech generation failed: {type(exc).__name__}: {exc}"
            )

    st.caption(
        "AI-generated guidance can contain mistakes. Verify important "
        "requirements and deadlines using the original document and "
        "responsible official authority."
    )

else:
    st.info(
        "Upload a document to get started. The explanation, source research, "
        "and voice output will appear here as they become available."
    )
