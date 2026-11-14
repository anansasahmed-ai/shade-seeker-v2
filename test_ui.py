import re
from playwright.sync_api import Page, expect


def test_shade_seeker_disambiguation_and_route_flow(page: Page):
    # 1. Navigate to local Streamlit server
    page.goto("http://localhost:8501")

    # 2. Authenticate
    password_input = page.get_by_label("Enter Password")
    password_input.fill("8749")
    password_input.press("Enter")

    # Wait for main app header to render
    expect(page.get_by_role("heading", name=re.compile("Shade Seeker"))).to_be_visible(timeout=15000)

    # 3. Test Form Guardrail + Agent Handoff with ambiguous destination ("San Jose")
    page.get_by_label("Origin").fill("San Francisco, CA")
    page.get_by_label("Destination").fill("San Jose")
    page.get_by_role("button", name="Calculate Shade").click()

    # Verify the app did NOT calculate a route yet and instead asked for clarification in chat
    expect(page.get_by_text(re.compile("California|Costa Rica|specify|clarify", re.IGNORECASE)).last).to_be_visible(
        timeout=20000
    )

    # 4. Clarify in the natural chat box and verify full shade calculation completes
    chat_input = page.get_by_placeholder(re.compile("Where are you traveling"))
    chat_input.fill("San Jose, CA leaving tomorrow at 2:00 PM by car")
    chat_input.press("Enter")

    # Verify shade percentage and seat side recommendation appear in the agent response
    expect(page.get_by_text(re.compile(r"\d+(\.\d+)?% shaded", re.IGNORECASE)).last).to_be_visible(
        timeout=30000
    )
    expect(page.get_by_text(re.compile(r"\b(LEFT|RIGHT|either side)\b", re.IGNORECASE)).last).to_be_visible(
        timeout=10000
    )
