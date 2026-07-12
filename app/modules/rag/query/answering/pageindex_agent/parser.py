import re

def parse_agent_response(text: str) -> tuple[str, str]:
    """
    Parse the agent's text response to separate reasoning (pre-thought) and the final answer.

    Strategy: locate the LAST </answer> closing tag, then find the LAST <answer> opening tag
    that appears *before* it.  Extracting the content between these two positions handles
    every problematic pattern the LLM can produce:

      Normal     : reasoning <answer>answer</answer>
                   → pre="reasoning", ans="answer"

      Multi-open : <answer>bad_start <answer>good_answer</answer>
                   → last </answer> at end, last <answer> before it is the inner one
                   → pre="<answer>bad_start", ans="good_answer"

      Nested     : <answer>outer <answer>inner</answer></answer>
                   → last </answer> at end, last <answer> before it is the inner one
                   → pre="<answer>outer", ans="inner"

      Truncation : reasoning <answer>partial...  (no closing tag)
                   → falls through to case 2: use last <answer> to end-of-text

      No tags    : fallback returns full text as answer

    Returns:
        tuple: (reasoning_text, final_answer_text)
    """
    # Strip common Gemini thinking artifacts (e.g. leading backtick-dot)
    text = re.sub(r"^`\.\n?", "", text).strip()

    # ── Case 1: at least one complete <answer>...</answer> pair exists ────────
    close_matches = list(re.finditer(r'</answer>', text, flags=re.IGNORECASE))
    if close_matches:
        last_close = close_matches[-1]

        # Search only the slice of text that precedes the last closing tag
        open_matches = list(re.finditer(r'<answer>', text[:last_close.start()], flags=re.IGNORECASE))
        if open_matches:
            last_open = open_matches[-1]
            pre_think = text[:last_open.start()].strip()
            answer = text[last_open.end():last_close.start()].strip()
            return pre_think, answer

        # Closing tag exists but no opening tag before it — unusual; treat preceding text as answer
        return "", text[:last_close.start()].strip()

    # ── Case 2: opening tag present but no closing tag (truncated response) ───
    all_opens = list(re.finditer(r'<answer>', text, flags=re.IGNORECASE))
    if all_opens:
        last_open = all_opens[-1]
        pre_think = text[:last_open.start()].strip()
        answer = text[last_open.end():].strip()
        return pre_think, answer

    # ── Case 3: no tags at all — return full text as answer ──────────────────
    return "", text.strip()
