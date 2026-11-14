import datetime
import time
import streamlit as st
import folium
from streamlit_folium import st_folium
from agent import chat, route_state
from map_visualizer import create_route_map

st.set_page_config(page_title="Shade Seeker AI", page_icon="🌞", layout="wide")
HARDCODED_PASSWORD = "8749"


def check_password() -> bool:
    if st.session_state.get("password_correct", False):
        return True
    
    st.markdown("## 🔒 Shade Seeker Login")
    pwd = st.text_input("Enter Password", type="password")
    if pwd == HARDCODED_PASSWORD:
        st.session_state["password_correct"] = True
        st.rerun()
    elif pwd:
        st.error("Incorrect password.")
    return False


if not check_password():
    st.stop()

st.title("🌞 Shade Seeker: Geospatial Solar & Transit Agent")

chat_col, map_col = st.columns([1.1, 0.9])
if "messages" not in st.session_state:
    st.session_state.messages = []


def process_and_rerun(user_input: str):
    st.session_state.messages.append({"role": "user", "content": user_input})
    with chat_col:
        with st.spinner("Thinking..."):
            try:
                response = chat.send_message(user_input)
                st.session_state.messages.append({"role": "assistant", "content": response.text})
            except Exception as e:
                st.session_state.messages.append({"role": "assistant", "content": f"⚠️ Error: {e}"})
    st.rerun()


with chat_col:
    st.subheader("🎯 Structured Journey Planner")

    with st.form("route_form"):
        form_origin = st.text_input("Origin", placeholder="e.g., San Francisco, CA")
        form_destination = st.text_input("Destination", placeholder="e.g., San Jose, CA")
        
        c1, c2 = st.columns(2)
        f_date = c1.date_input("Date", value=None)
        f_time = c2.time_input("Time", value=None)
        
        f_mode = st.selectbox("Mode", ["Car / Private Bus (DRIVE)", "Public Bus / Train (TRANSIT)"])
        submitted = st.form_submit_button("Calculate Shade")

    if submitted:
        if not form_origin or not form_destination:
            st.error("Provide both origin and destination.")
        else:
            mode = "TRANSIT" if "TRANSIT" in f_mode else "DRIVE"
            dt_str = f" departing at {f_date.isoformat()}T{f_time.strftime('%H:%M:%S')}" if f_date else ""
            process_and_rerun(f"Find route shade from {form_origin} to {form_destination} using {mode}{dt_str}")

    st.markdown("---")
    st.subheader("💬 Open Chat")

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Where are you traveling?"):
        process_and_rerun(prompt)

with map_col:
    st.subheader("🗺️ Route Map")
    coords = route_state.get("coords")
    m = create_route_map(coords) if coords else folium.Map(location=[17.0753, -96.7236], zoom_start=7)
    if not coords:
        st.info("Enter a route to view map.")
    st_folium(m, width=None, height=600)
