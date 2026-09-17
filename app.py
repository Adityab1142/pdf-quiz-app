import streamlit as st
import fitz  # PyMuPDF
from PIL import Image
import io
import json
import sqlite3
import pandas as pd
from datetime import datetime
import google.generativeai as genai

st.set_page_config(page_title="Mobile Quiz App", layout="centered")

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect("quiz_data.db")
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS quiz_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            score INTEGER,
            total_questions INTEGER,
            timestamp TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_score(username, score, total):
    conn = sqlite3.connect("quiz_data.db")
    c = conn.cursor()
    timestamp = datetime.now().strftime("%d %b %Y, %I:%M %p")
    c.execute(
        "INSERT INTO quiz_history (username, score, total_questions, timestamp) VALUES (?, ?, ?, ?)",
        (username, score, total, timestamp)
    )
    conn.commit()
    conn.close()

def load_history():
    conn = sqlite3.connect("quiz_data.db")
    df = pd.read_sql_query("SELECT username as Name, score as Score, total_questions as Total, timestamp as Date FROM quiz_history ORDER BY id DESC", conn)
    conn.close()
    return df

init_db()

# --- PDF & VISION PROCESSING ---
def extract_pdf_pages_as_images(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images = []
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        img = Image.open(io.BytesIO(pix.tobytes()))
        images.append(img)
    return images

def analyze_page_layout(image):
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = """
    Analyze this page of multiple-choice questions. 
    Find each question's vertical start and end points as a percentage of height (0.0 to 1.0).
    Include question text, options, and diagrams within these bounds.
    If an answer key is visible, extract the correct option (A, B, C, or D). If not, leave it null.
    
    Return EXACTLY this JSON format:
    [
        {"q_num": 1, "y_start": 0.10, "y_end": 0.25, "answer": "B"}
    ]
    """
    response = model.generate_content([image, prompt])
    try:
        json_str = response.text.strip().removeprefix("```json").removesuffix("```").strip()
        return json.loads(json_str)
    except Exception:
        return []

# --- APP UI ---
st.title("📱 PDF Quiz Generator")

# Mobile Tabs for Clean Navigation
tab_quiz, tab_history = st.tabs(["📝 Quiz", "🏆 History"])

with tab_quiz:
    # Check secrets first, otherwise ask for input
    api_key = st.secrets.get("GEMINI_API_KEY", None)
    if not api_key:
        with st.expander("🔑 Enter Gemini API Key"):
            api_key = st.text_input("API Key", type="password", placeholder="AIzaSy...")

    uploaded_file = st.file_uploader("Upload MCQ PDF from phone", type=["pdf"])

    if uploaded_file and api_key:
        genai.configure(api_key=api_key)
        
        if "quiz_data" not in st.session_state:
            st.session_state.quiz_data = []
            
            with st.spinner("Rendering PDF pages..."):
                pages = extract_pdf_pages_as_images(uploaded_file.read())
                
            with st.spinner("Cropping questions and answers..."):
                for page_img in pages:
                    width, height = page_img.size
                    layout_data = analyze_page_layout(page_img)
                    
                    for item in layout_data:
                        top = int(item['y_start'] * height)
                        bottom = int(item['y_end'] * height)
                        cropped_img = page_img.crop((0, top, width, bottom))
                        
                        st.session_state.quiz_data.append({
                            "image": cropped_img,
                            "answer": item.get('answer'),
                            "q_num": item.get('q_num', '1')
                        })
            st.success("Quiz ready!")

    if "quiz_data" in st.session_state and st.session_state.quiz_data:
        st.divider()
        username = st.text_input("Your Name:", value="Learner")
        
        user_responses = {}
        for idx, q in enumerate(st.session_state.quiz_data):
            st.markdown(f"**Question {idx + 1}**")
            # Automatically scales to mobile screen width
            st.image(q['image'], use_container_width=True)
            
            # Horizontal radio looks like tap buttons on mobile
            choice = st.radio(
                f"Option for Q{idx + 1}:",
                options=["Skip", "A", "B", "C", "D"],
                horizontal=True,
                key=f"q_{idx}"
            )
            user_responses[idx] = choice
            st.write("")

        if st.button("Submit & Save Results", use_container_width=True):
            score = 0
            total = len(st.session_state.quiz_data)
            
            for idx, q in enumerate(st.session_state.quiz_data):
                ans = q.get('answer')
                if ans and user_responses[idx] == ans.upper():
                    score += 1
                    
            st.balloons()
            st.metric(label="Your Score", value=f"{score} / {total}")
            save_score(username, score, total)
            st.success("Results saved to history tab!")

with tab_history:
    st.subheader("Previous Attempts")
    history_df = load_history()
    if not history_df.empty:
        st.dataframe(history_df, use_container_width=True, hide_index=True)
    else:
        st.info("No attempts recorded yet.")
