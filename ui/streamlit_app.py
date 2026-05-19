from __future__ import annotations

import requests
import streamlit as st


st.set_page_config(page_title="Optisweep Phase 0", page_icon=None)
st.title("Optisweep AI Support Assistant Phase 0")

api_url = st.text_input("FastAPI URL", "http://127.0.0.1:8000/troubleshoot")
session_id = st.text_input("Session ID", "demo-session")
message = st.text_area(
    "Troubleshooting symptoms",
    "AGVs stopped, no RMS alarms, all tippers heartbeat timeout, hospital tote removal hangs, system active but frozen",
)

if st.button("Troubleshoot"):
    response = requests.post(api_url, json={"session_id": session_id, "user_message": message}, timeout=30)
    response.raise_for_status()
    payload = response.json()
    st.subheader("Response")
    st.write(payload["final_response"])
    st.subheader("Workflow")
    st.json(payload["workflow_state"])
    st.subheader("Citations")
    st.json(payload["citations"])
    st.subheader("Escalation")
    st.write(payload["escalation_required"])
    st.write(payload.get("escalation_reason"))
