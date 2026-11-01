"""Filter vision-model noise from extracted profile prompts."""

from __future__ import annotations

import re

from wingman.models import ProfileAnalysis, PromptItem

_META_PROMPT_RE = re.compile(
    r"what is the (name|age|location|basic information|basic info|person'?s name|person'?s age)"
    r"|who is (this|the person)"
    r"|where is the person"
    r"|what is the person (wearing|doing|holding)"
    r"|identify the person",
    re.I,
)

_GARBAGE_PROMPT_RE = re.compile(
    r"shows thoughtful signals"
    r"|\bthoughtful signals\b"
    r"|basic information about the person"
    r"|silent status|google weather|silent profile",
    re.I,
)

_HINGE_UI_RE = re.compile(
    r"keep going"
    r"|learning who you like|we'?re learning who you like"
    r"|learning your type"
    r"|one like goes a long way",
    re.I,
)

_GARBAGE_ANSWER_RE = re.compile(
    r"^(not visible|unknown|unreadable|n/a|none|\(unreadable\))$"
    r"|^the person is (wearing|standing|sitting|holding)",
    re.I,
)

_FABRICATED_ANSWER_RE = re.compile(
    r"i'?m looking for a (partner|relationship|someone)"
    r"|keep up with my busy schedule"
    r"|share my interests in technology and travel"
    r"|enjoys spending time outdoors"
    r"|has a sense of humor"
    r"|shares my passion"
    r"|passion for fashion"
    r"|enjoys exploring new places"
    r"|looking for someone who",
    re.I,
)

_SCHEMA_NAME_GARBAGE = frozenset({
    "",
    "unknown",
    "lowercase first name or empty",
    "first name or empty",
    "name or empty",
})

_WEAK_ANSWERS = frozenset({"unknown", "unreadable", "n/a", "none", "", "not visible", "(unreadable)"})

_PROMPT_STEM_ANSWERS = frozenset({
    "the way to win me over is",
    "the key to my heart is",
    "let's break the ice by",
    "all i ask is that you",
    "me in the wild",
    "we're learning who you like.",
    "we're learning who you like",
    "a",
})

# When vision merges Hinge prompt stem + answer into one duplicated string,
# or embeds the answer in prompt_text with an empty answer field.
_HINGE_SPLITTERS: tuple[tuple[str, str], ...] = (
    ("the way to win me over is", "The way to win me over is"),
    ("the key to my heart is", "The key to my heart is"),
    ("i geek out on", "I geek out on"),
    ("my simple pleasures", "My simple pleasures"),
    ("i go crazy for", "I go crazy for"),
    ("together we could", "Together we could"),
    ("the dorkiest thing about me is", "The dorkiest thing about me is"),
    ("my most irrational fear is", "My most irrational fear is"),
    ("my most irrational fear", "My most irrational fear is"),
    ("i won't shut up about", "I won't shut up about"),
    ("let's break the ice by", "Let's break the ice by"),
    ("all i ask is that you", "All I ask is that you"),
    ("this year, i really want to", "This year, I really want to"),
    ("i recently discovered that", "I recently discovered that"),
    ("worst idea i've ever had", "Worst idea I've ever had"),
    ("dating me is like", "Dating me is like"),
    ("an award my family would give me", "An award my family would give me"),
    ("me during fashion week", "Me during Fashion Week"),
)


def _norm(text: str) -> str:
    return " ".join(text.strip().lower().split())


def clean_extracted_name(name: str) -> str:
    """Drop schema-placeholder names leaked from vision JSON templates."""
    n = str(name or "").strip().lower()
    if not n or n in _SCHEMA_NAME_GARBAGE:
        return "unknown"
    if "first name or empty" in n or "lowercase first name" in n:
        return "unknown"
    return n


def repair_prompt_answer(prompt_text: str, answer: str) -> tuple[str, str]:
    """Recover answer embedded in prompt_text when vision left answer empty."""
    q = prompt_text.strip()
    a = answer.strip()
    if a and a.lower() not in _WEAK_ANSWERS:
        return q, a
    lower = q.lower()
    for prefix_lower, prompt_label in _HINGE_SPLITTERS:
        if lower.startswith(prefix_lower) and len(q) > len(prefix_lower) + 4:
            remainder = q[len(prefix_lower) :].strip(" .:-")
            if len(remainder) >= 4 and _norm(remainder) != prefix_lower:
                return prompt_label, remainder
    return q, a


def split_merged_hinge_prompt(prompt_text: str, answer: str) -> tuple[str, str]:
    """Split vision-merged prompt+answer when both fields are identical."""
    q = prompt_text.strip()
    a = answer.strip()
    if _norm(q) != _norm(a):
        return q, a
    lower = q.lower()
    for prefix_lower, prompt_label in _HINGE_SPLITTERS:
        if lower.startswith(prefix_lower):
            remainder = q[len(prefix_lower) :].strip(" .:-")
            if len(remainder) >= 3 and _norm(remainder) != prefix_lower:
                return prompt_label, remainder
    return q, a


def is_prompt_stem_answer(answer: str) -> bool:
    """True when answer is another Hinge prompt title, not her real reply."""
    a = _norm(answer).strip(" .")
    if a in _PROMPT_STEM_ANSWERS:
        return True
    for stem in _PROMPT_STEM_ANSWERS:
        if a == stem.rstrip("."):
            return True
    return False


def is_fabricated_answer(prompt_text: str, answer: str) -> bool:
    """Generic LLM-hallucinated answers that don't match Hinge voice."""
    return bool(_FABRICATED_ANSWER_RE.search(answer))


def is_garbled_cross_prompt(prompt_text: str, answer: str) -> bool:
    """OCR bleed between adjacent prompt cards."""
    q = prompt_text.lower()
    a = answer.lower()
    if "me in the wild" in q and "ask" in a and len(a) < 24:
        return True
    if "debating about our favourite font" in q and not answer.strip():
        return True
    if "talking about the reddit lamp story" in q and not answer.strip():
        return True
    if q.startswith("i geek out on") and a.startswith("i geek out on"):
        return True
    if "don't hate me" in q and "award my family" in a:
        return True
    if "pineapple" in q and "award my family" in a:
        return True
    if "me during fashion week" in q and _norm(q) == _norm(a):
        return True
    if "dating me is like" in q and len(a) < 8:
        return True
    return False


def is_meta_prompt(prompt_text: str, answer: str) -> bool:
    """True when the prompt looks like model self-QA, not a Hinge prompt."""
    q = prompt_text.strip()
    a = answer.strip()
    a_lower = a.lower()
    if not q:
        return True
    if _HINGE_UI_RE.search(q) or _HINGE_UI_RE.search(a):
        return True
    if _GARBAGE_PROMPT_RE.search(q):
        return True
    if is_prompt_stem_answer(a):
        return True
    if is_fabricated_answer(q, a):
        return True
    if is_garbled_cross_prompt(q, a):
        return True
    if _META_PROMPT_RE.search(q):
        if a_lower in _WEAK_ANSWERS or _norm(q) == _norm(a):
            return True
        if len(a_lower) <= 12 and a_lower in ("vishakha", "unknown", "v"):
            return True
        if _GARBAGE_ANSWER_RE.search(a):
            return True
    if _GARBAGE_ANSWER_RE.search(a):
        return True
    if _norm(q) == _norm(a):
        if _GARBAGE_PROMPT_RE.search(q):
            return True
        if len(a) < 12:
            return True
        if a_lower.startswith("the way to win me over") or a_lower.startswith("the key to my heart"):
            return True
        if "student at student" in a_lower:
            return True
    return False


def is_usable_prompt(prompt_text: str, answer: str) -> bool:
    a = answer.strip()
    if not a or a.lower() in _WEAK_ANSWERS:
        return False
    if is_meta_prompt(prompt_text, answer):
        return False
    return True


def normalize_prompt_item(item: PromptItem) -> PromptItem:
    """Split merged prompt/answer pairs and trim noise."""
    q, a = repair_prompt_answer(item.prompt_text, item.answer)
    q, a = split_merged_hinge_prompt(q, a)
    return PromptItem(
        prompt_text=q,
        answer=a,
        readable=item.readable,
    )


def prompt_quality_score(item: PromptItem) -> int:
    """Lower score = stronger opener hook (1 is best)."""
    q = item.prompt_text.lower()
    a = item.answer.lower()
    blob = f"{q} {a}"

    if "bacchon" in a or "hone wala baap" in a:
        return 1
    if "bud magnum" in a or "magnum" in a and "bud" in a:
        return 1
    if "law school" in a:
        return 1
    if "drunk ciggs" in a or "ciggs don't count" in a:
        return 1
    if "pineapple" in a and "pizza" in a:
        return 1
    if "guys who can cook" in a or ("cook" in a and "weirdly attracted" in q):
        return 2
    if "best arguments" in a or "coming up with" in a:
        return 1
    if "overdressed" in a:
        return 2
    if "greek philosophers" in a or "diss tracks" in a:
        return 1
    if "pythagorean" in a:
        return 1
    if "yap" in a and ("niche" in a or "nerdy" in a):
        return 1
    if "yapping" in a or ("yap" in a and "skill" in q):
        return 1
    if "pun relay" in a or "break the ice" in q:
        return 2
    if "homies" in a or "recreational facility" in a:
        return 2
    if "bob" in a and "stuart" in a:
        return 2
    if "un-funny men" in a or "regressive views" in a:
        return 2
    if "life partner" in q and not is_fabricated_answer(q, item.answer):
        return 3
    if "don't hate me" in q or ("laugh" in a and "serious" in a):
        return 2
    if "spontaneous" in a or "asf" in a:
        return 2
    if "perfume" in a:
        return 3
    if "go to face" in a or "go to top" in a:
        return 4
    if "dating goals" in q and "liberal" in a:
        return 3
    if "unusual skill" in q:
        return 2
    if "stoic" in a:
        return 1
    if "mountain" in a or "trip to the" in a:
        return 3
    if "cookie" in a or "chocolate" in a:
        return 3
    if "nbhd" in a or "neighbourhood" in a or "neighborhood" in a:
        return 2
    if "making things out of things" in a or "making things" in a:
        return 2
    if len(a) <= 40 and _norm(item.prompt_text) != _norm(item.answer):
        return 5
    if _norm(item.prompt_text) == _norm(item.answer):
        return 8
    return 6


def clean_prompts(profile: ProfileAnalysis) -> list[PromptItem]:
    """Return real Hinge prompts with usable answers, normalized and deduped."""
    cleaned: list[PromptItem] = []
    seen: set[str] = set()
    for raw in profile.prompts:
        item = normalize_prompt_item(raw)
        if not is_usable_prompt(item.prompt_text, item.answer):
            continue
        key = f"{_norm(item.prompt_text)}|{_norm(item.answer)}"
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(item)
    cleaned.sort(key=prompt_quality_score)
    return cleaned


def clean_interest_signals(profile: ProfileAnalysis) -> list[str]:
    """Drop signals that duplicate prompt text or basic demographics."""
    prompts = clean_prompts(profile)
    prompt_words = {
        w
        for p in prompts
        for w in re.findall(r"[a-z0-9']+", f"{p.prompt_text} {p.answer}".lower())
        if len(w) > 3
    }
    demo_noise = {
        "straight", "woman", "man", "rajasthan", "figuring", "dating", "goals",
        "relationship", "type", "political", "opinions", "posing", "photo",
        "thoughtful", "signals", "visible", "student", "learning", "technology",
        "travel", "schedule", "busy", "showing", "restaurant", "setting",
    }
    garbage_re = re.compile(
        r"standing on a staircase|wearing a black|dimly lit|not visible"
        r"|learning who you like|learning your type|one like goes a long way"
        r"|shows thoughtful signals|google weather|silent",
        re.I,
    )
    out: list[str] = []
    seen: set[str] = set()
    for raw in profile.interest_signals:
        sig = str(raw).strip()
        if not sig:
            continue
        key = sig.lower()
        if key in seen:
            continue
        if key in demo_noise:
            continue
        if garbage_re.search(sig):
            continue
        if len(sig) > 80:
            continue
        if key in prompt_words:
            continue
        seen.add(key)
        out.append(sig)
    return out


def profile_is_active_now(profile: ProfileAnalysis) -> bool:
    """True when Hinge shows she is Active now (better match/reply odds)."""
    parts = [
        profile.basic_info,
        profile.summary,
        " ".join(profile.interest_signals),
        " ".join(profile.evidence_bullets[:6]),
    ]
    blob = " ".join(p for p in parts if p).lower()
    return "active now" in blob
