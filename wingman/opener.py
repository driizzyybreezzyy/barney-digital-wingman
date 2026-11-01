"""Generate and validate three opener candidates."""

from __future__ import annotations

import re
from dataclasses import dataclass

from judge_common import resolve_voice

import config
from wingman.llm import OPENERS_NUM_PREDICT, text_json
from wingman.models import CompatibilityResult, OpenerCandidate, ProfileAnalysis, PromptItem
from wingman.personality import banned_phrases, natural_phrase_hints, personality_prompt_section
from wingman.profile_clean import clean_interest_signals, clean_prompts, prompt_quality_score

_STYLES = ("playful", "clever", "flirty")
_MAX_LEN = 200
_MIN_LEN = 28

_START_BANNED = re.compile(r"^\s*(hey|hi|hello)\b", re.I)

INTERVIEW_PATTERNS = [
    r"^what'?s the\b",
    r"^what'?s your\b",
    r"^what is the\b",
    r"^what is your\b",
    r"^how do you\b",
    r"^how would you\b",
    r"^tell me\b",
    r"^can you\b",
    r"^could you\b",
    r"^have you ever\b",
    r"^do you ever\b",
    r"^would you\b",
    r"^are you\b",
    r"^may i ask\b",
    r"^quick question\b",
    r"\?$",  # pure question opener ending only with ?
    r"sounds like a fun adventure",
    r"sounds like fun\b",
    r"^figuring out my dating goals\b",
]

GENERIC_PATTERNS = [
    r"\blooks amazing\b",
    r"\bso beautiful\b",
    r"\bhey beautiful\b",
    r"\bhi beautiful\b",
    r"\bhow are you\b",
    r"\bwhat are you doing\b",
    r"\bwhat'?s up\b",
    r"\byou'?re gorgeous\b",
    r"\bcaught my eye\b",
    r"\blove that\b",
    r"\bobsessed\b",
    r"\biconic\b",
    r"\bpickup line\b",
    r"\bgenuinely\b",
    r"\bhonestly truly\b",
    r"is either .+ or .+\. i'?m leaning",
    r"either a secret or a bold claim",
    r"either perfect chaos or you",
    r"either a real-life partner or chaos",
    r"until proven wrong",
    r"^this year, i really want to",
    r"i'?m leaning to believe",
    r"match the energy",
    r"dream come true or you",
    r"is unhinged\. respect\.?\s*$",
    r"\bunhinged\. respect\b",
]

APPEARANCE_PATTERNS = [
    r"\bhair\b",
    r"\bwavy\b",
    r"\bbeautiful\b",
    r"\bpretty\b",
    r"\bcute\b",
    r"\bhot\b",
    r"\bgorgeous\b",
    r"\bsmile\b",
    r"\blook cool\b",
    r"\blook amazing\b",
    r"\blook so cool\b",
    r"\bthumbs up\b",
    r"\bin the car\b",
    r"\byour outfit\b",
    r"\byour dress\b",
    r"\bunique style\b",
    r"\battractive\b",
    r"\bselfie\b",
    r"\bphoto\b",
    r"\bpicture\b",
]

_STYLE_GUIDE = {
    "playful": (
        "PLAYFUL: teasing troublemaker, mild ragebait. Bold claim, either/or, "
        "suspiciously specific, or challenge. Vary endings — NO 'unhinged. respect' template. "
        "Example: 'a bud magnum to win you over is either elite or chaos. i'm taking that as a challenge'"
    ),
    "clever": (
        "CLEVER: witty hot take reframing her answer. Smart observation with edge. "
        "NOT a quiz. Example: 'law school as worst idea is the most honest hinge answer i've seen in a while'"
    ),
    "flirty": (
        "FLIRTY: confident direct flirt, bold 8/10. Imply chemistry or trouble. "
        "NOT crude. Do NOT use 'match the energy'. "
        "Example: 'law school as your worst idea? dangerous combo. i'd probably match it'"
    ),
}

_FALLBACK_OPENERS: dict[tuple[str, str], str] = {
    ("playful", "yapping"): (
        "yapping listed as a skill is bold. i need proof you're actually elite at it"
    ),
    ("playful", "serious"): (
        "laughing at serious situations is a bold claim. i'm taking that as a challenge"
    ),
    ("playful", "liberal"): (
        "liberal as your whole dating-goals answer is suspiciously specific for hinge. defend it"
    ),
    ("clever", "yapping"): (
        "yapping as an unusual skill is the most honest hinge answer i've seen in a while"
    ),
    ("clever", "serious"): (
        "don't hate me if i say laughing at serious situations is either elite humor or pure chaos"
    ),
    ("clever", "liberal"): (
        "liberal dating goals on hinge is a whole personality statement. that's suspiciously specific"
    ),
    ("flirty", "yapping"): (
        "yapping as a skill plus that energy? that's trouble. i'd probably match it"
    ),
    ("flirty", "serious"): (
        "you laugh at serious situations? dangerous combo. i'd probably match it"
    ),
    ("flirty", "liberal"): (
        "liberal dating goals and that vibe — you're either very fun or i'm walking into an argument. leaning fun"
    ),
    ("playful", "life_partner"): (
        "bacchon ka hone wala baap as a life partner answer is the boldest dad joke on hinge i've seen"
    ),
    ("clever", "life_partner"): (
        "bacchon ka hone wala baap as a life partner answer is the boldest dad joke on hinge i've seen"
    ),
    ("flirty", "life_partner"): (
        "future baap energy on a life partner prompt? that's trouble. i'd probably match it"
    ),
    ("playful", "spontaneous"): (
        "spontaneous asf is either elite or pure chaos. which one are we testing first"
    ),
    ("clever", "spontaneous"): (
        "spontaneous asf as your whole win-me-over plan is suspiciously specific for hinge"
    ),
    ("flirty", "spontaneous"): (
        "spontaneous asf energy? that's trouble. i'd probably match it"
    ),
    ("playful", "perfume"): (
        "good perfumes as the key to your heart is suspiciously specific. what's the rotation"
    ),
    ("clever", "perfume"): (
        "perfumes as the key to your heart is a whole personality statement. defend the top pick"
    ),
    ("flirty", "perfume"): (
        "good perfumes unlocking your heart? dangerous combo. i'd probably match it"
    ),
    ("playful", "greek_philosophers"): (
        "greek philosophers walking so diss tracks could run is either elite lore or chaos. defend it"
    ),
    ("clever", "greek_philosophers"): (
        "that greek philosophers to diss tracks pipeline is the most specific hinge answer i've seen"
    ),
    ("flirty", "greek_philosophers"): (
        "greek philosophers plus diss track energy? that's trouble. i'd probably match it"
    ),
    ("playful", "pythagorean"): (
        "pythagorean theorem as your whole year goal is either genius or a cry for help. which one"
    ),
    ("clever", "pythagorean"): (
        "pythagorean theorem as your whole year goal is suspiciously specific for hinge"
    ),
    ("flirty", "pythagorean"): (
        "pythagorean theorem brain? dangerous combo. i'd probably match it"
    ),
    ("playful", "pun_relay"): (
        "pun relay as the icebreaker is either elite or chaos. which one are we running first"
    ),
    ("clever", "pun_relay"): (
        "a pun relay to break the ice is the boldest hinge strategy i've seen in a while"
    ),
    ("flirty", "pun_relay"): (
        "pun relay energy on a break-the-ice prompt? that's trouble. i'd probably match it"
    ),
    ("playful", "yap_niche"): (
        "yap about niche nerdy interests is suspiciously specific. what's the first topic"
    ),
    ("clever", "yap_niche"): (
        "all you ask is nerdy yap? that's either perfect or i'm walking into a lecture. leaning perfect"
    ),
    ("flirty", "yap_niche"): (
        "niche nerdy yap energy? that's trouble. i'd probably match it"
    ),
    ("playful", "homies"): (
        "building a recreational facility for all the homies is either elite or chaos. what's phase one"
    ),
    ("clever", "homies"): (
        "a recreational facility for all the homies as a life goal is suspiciously specific for hinge"
    ),
    ("playful", "minions"): (
        "bob kevin and stuart is either elite taste or chaos. which one"
    ),
    ("clever", "minions"): (
        "going crazy for bob kevin and stuart is the most honest minions answer on hinge"
    ),
    ("playful", "mountains"): (
        "mountains as the whole year plan is bold. already booked or still fantasy"
    ),
    ("clever", "mountains"): (
        "whole year locked in for mountains is bold. defend the pick"
    ),
    ("flirty", "mountains"): (
        "mountains trip energy on your year plan? that's trouble. i'd probably match it"
    ),
    ("playful", "cookies"): (
        "double chocolate chip cookies on a hinge profile is suspiciously specific. what's the ranking"
    ),
    ("clever", "cookies"): (
        "double chocolate chip cookies as a whole personality statement. defend it"
    ),
    ("playful", "stoic"): (
        "you being stoic as an irrational fear is a bold claim. i'm taking that as a challenge"
    ),
    ("clever", "stoic"): (
        "you being stoic as the irrational fear answer is suspiciously specific for hinge"
    ),
    ("flirty", "stoic"): (
        "stoic as an irrational fear? dangerous combo. i'd probably match it"
    ),
    ("playful", "nbhd"): (
        "the nbhd on simple pleasures is suspiciously specific. what's the rotation"
    ),
    ("clever", "nbhd"): (
        "the nbhd as a simple pleasure is a whole personality statement. defend it"
    ),
    ("playful", "making_things"): (
        "making things out of things is either a hobby or a red flag. leaning hobby"
    ),
    ("clever", "making_things"): (
        "making things out of things on a hinge prompt is the most honest answer i've seen in a while"
    ),
    ("flirty", "making_things"): (
        "making things out of things energy? that's trouble. i'd probably match it"
    ),
    ("playful", "bud_magnum"): (
        "a bud magnum to win you over is either elite or chaos. i'm taking that as a challenge"
    ),
    ("clever", "bud_magnum"): (
        "bud magnum as your whole win-me-over plan is suspiciously specific for hinge"
    ),
    ("flirty", "bud_magnum"): (
        "bud magnum energy on a win-me-over prompt? that's trouble. i'd probably match it"
    ),
    ("playful", "law_school"): (
        "law school as worst idea ever had is either honest or a flex. defend it"
    ),
    ("clever", "law_school"): (
        "worst idea being law school is the most honest hinge answer i've seen in a while"
    ),
    ("flirty", "law_school"): (
        "law school as your worst idea? dangerous combo. i'd probably match it"
    ),
    ("playful", "drunk_ciggs"): (
        "drunk ciggs don't count is suspiciously specific. what's the real rule"
    ),
    ("clever", "drunk_ciggs"): (
        "recently discovering drunk ciggs don't count is suspiciously specific for hinge"
    ),
    ("playful", "charlotte_york"): (
        "charlotte york energy on a dating-me prompt is either elite or chaos. defend it"
    ),
    ("clever", "charlotte_york"): (
        "dating you being charlotte york basically is the most specific SATC answer on hinge"
    ),
    ("flirty", "charlotte_york"): (
        "charlotte york energy? that's trouble. i'd probably match it"
    ),
    ("playful", "family_arguments"): (
        "coming up with best arguments as a family award is either elite or chaos. defend it"
    ),
    ("clever", "family_arguments"): (
        "best arguments as a family award is suspiciously specific. what's the winning case"
    ),
    ("flirty", "family_arguments"): (
        "family award for best arguments? dangerous combo. i'd probably match it"
    ),
    ("playful", "overdressed"): (
        "being overdressed as an irrational fear is a bold claim. defend it"
    ),
    ("clever", "overdressed"): (
        "irrational fear being overdressed is either fashion sense or chaos. which one"
    ),
}


@dataclass
class HookContext:
    label: str
    detail: str
    evidence: str
    priority: int
    anchor_words: tuple[str, ...]
    hook_key: str = "generic"


def _hook_key(label: str, detail: str) -> str:
    blob = f"{label} {detail}".lower()
    if "bacchon" in blob or "hone wala baap" in blob:
        return "life_partner"
    if "yapping" in blob or "yap" in blob:
        return "yapping"
    if "spontaneous" in blob or "asf" in blob:
        return "spontaneous"
    if "perfume" in blob:
        return "perfume"
    if "serious" in blob or "laugh" in blob or "don't hate me" in blob:
        return "serious"
    if "liberal" in blob or "dating goals" in blob:
        return "liberal"
    if "go to face" in blob or "go to top" in blob:
        return "goto_look"
    if "greek" in blob or "diss tracks" in blob or "philosophers" in blob:
        return "greek_philosophers"
    if "pythagorean" in blob:
        return "pythagorean"
    if "pun relay" in blob or "break the ice" in blob:
        return "pun_relay"
    if "niche" in blob and "nerdy" in blob:
        return "yap_niche"
    if "homies" in blob or "recreational facility" in blob:
        return "homies"
    if "bob" in blob and "stuart" in blob:
        return "minions"
    if "mountain" in blob or "trip to the" in blob:
        return "mountains"
    if "chocolate" in blob and "cookie" in blob:
        return "cookies"
    if "stoic" in blob:
        return "stoic"
    if "nbhd" in blob or "neighbourhood" in blob or "neighborhood" in blob:
        return "nbhd"
    if "making things" in blob:
        return "making_things"
    if "bud magnum" in blob or ("magnum" in blob and "bud" in blob):
        return "bud_magnum"
    if "law school" in blob:
        return "law_school"
    if "drunk ciggs" in blob or "ciggs don't count" in blob:
        return "drunk_ciggs"
    if "charlotte york" in blob:
        return "charlotte_york"
    if "best arguments" in blob or "coming up with" in blob:
        return "family_arguments"
    if "overdressed" in blob:
        return "overdressed"
    if "un-funny" in blob or "regressive" in blob:
        return "irrational_fear"
    return "generic"


def _anchor_words(label: str, detail: str) -> tuple[str, ...]:
    words: set[str] = set()
    blob = f"{label} {detail}".lower()
    for w in re.findall(r"[a-z0-9']+", blob):
        if len(w) > 3:
            words.add(w)
    if "yapping" in blob or "yap" in blob:
        words.update({"yapping", "yap"})
    if "laugh" in blob or "serious" in blob:
        words.update({"laugh", "laughing", "serious", "situations"})
    if "liberal" in blob:
        words.add("liberal")
    if "bacchon" in blob or "baap" in blob:
        words.update({"bacchon", "baap", "life", "partner", "unhinged"})
    if "spontaneous" in blob or "asf" in blob:
        words.update({"spontaneous", "asf", "chaos", "energy"})
    if "perfume" in blob:
        words.update({"perfume", "perfumes", "heart"})
    if "greek" in blob or "philosophers" in blob or "diss" in blob:
        words.update({"greek", "philosophers", "diss", "tracks", "unhinged"})
    if "pythagorean" in blob:
        words.update({"pythagorean", "theorem", "unhinged"})
    if "pun" in blob:
        words.update({"pun", "relay", "ice", "chaos"})
    if "niche" in blob or "nerdy" in blob:
        words.update({"niche", "nerdy", "yap", "interests"})
    if "homies" in blob:
        words.update({"homies", "recreational", "facility", "unhinged"})
    if "bob" in blob or "stuart" in blob:
        words.update({"bob", "kevin", "stuart", "chaos"})
    if "mountain" in blob:
        words.update({"mountains", "mountain", "trip", "bold", "booked", "fantasy"})
    if "cookie" in blob or "chocolate" in blob:
        words.update({"chocolate", "cookies", "chip", "double"})
    if "stoic" in blob:
        words.update({"stoic", "irrational", "fear", "unhinged"})
    if "nbhd" in blob:
        words.update({"nbhd", "simple", "pleasures", "rotation"})
    if "making things" in blob:
        words.update({"making", "things"})
    if "charlotte" in blob or "york" in blob:
        words.update({"charlotte", "york", "elite", "chaos"})
    if "arguments" in blob:
        words.update({"arguments", "family", "award", "elite", "chaos", "defend"})
    if "overdressed" in blob:
        words.update({"overdressed", "fear", "bold", "fashion"})
    return tuple(sorted(words))


def _prompt_priority(prompt: PromptItem) -> int:
    return prompt_quality_score(prompt)


def _evidence_for_prompt(prompt: PromptItem) -> str:
    q = prompt.prompt_text.strip()
    a = prompt.answer.strip()
    if "bacchon" in a.lower() or "life partner" in q.lower():
        return f'Her Hinge prompt "{q}" is answered with "{a}".'
    if "yapping" in a.lower() or "yap" in a.lower():
        return f'They list "{a}" as an unusual skill on their dating profile.'
    if "don't hate me" in q.lower():
        return f'Her Hinge prompt "{q}" is answered with "{a}".'
    if "dating goals" in q.lower():
        return f'She answered the prompt "{q}" with "{a}".'
    return f'Visible prompt: "{q}" — answer: "{a}".'


_INTEREST_GENERIC = frozenset({
    "travel", "mountains", "pet", "tech", "active now", "signals active now",
    "learning who you like", "break the ice by",
})


def _interest_hook_candidates(profile: ProfileAnalysis, seen: set[str]) -> list[HookContext]:
    """Backup hooks from cleaned interests when vision missed prompt cards."""
    out: list[HookContext] = []
    for sig in clean_interest_signals(profile):
        detail = sig.strip()
        key = detail.lower()
        if not detail or key in seen or key in _INTEREST_GENERIC:
            continue
        if len(detail) < 10:
            continue
        seen.add(key)
        out.append(
            HookContext(
                label=detail[:50],
                detail=detail,
                evidence=f'Profile interest/signal: "{detail}".',
                priority=6,
                anchor_words=_anchor_words(detail, detail),
                hook_key=_hook_key(detail, detail),
            )
        )
    return out


def rank_hooks_for_openers(profile: ProfileAnalysis) -> list[HookContext]:
    ranked: list[HookContext] = []
    seen_details: set[str] = set()

    for prompt in sorted(clean_prompts(profile), key=_prompt_priority):
        detail = prompt.answer.strip()
        if not detail:
            continue
        key = detail.lower()
        if key in seen_details:
            continue
        seen_details.add(key)
        label = prompt.prompt_text.strip()[:60] or detail[:40]
        ranked.append(
            HookContext(
                label=label,
                detail=detail,
                evidence=_evidence_for_prompt(prompt),
                priority=_prompt_priority(prompt),
                anchor_words=_anchor_words(label, detail),
                hook_key=_hook_key(label, detail),
            )
        )

    if len(ranked) < 3:
        for hook in _interest_hook_candidates(profile, seen_details):
            ranked.append(hook)
            if len(ranked) >= 3:
                break

    ranked.sort(key=lambda h: h.priority)
    return ranked[:4]


def _assign_hooks(hooks: list[HookContext]) -> dict[str, HookContext]:
    if not hooks:
        fallback = HookContext(
            label="profile",
            detail="profile detail",
            evidence="Profile has readable prompt content.",
            priority=99,
            anchor_words=("profile",),
            hook_key="generic",
        )
        return {s: fallback for s in _STYLES}

    primary = hooks[0]
    secondary = hooks[1] if len(hooks) > 1 else primary
    tertiary = hooks[2] if len(hooks) > 2 else secondary
    return {
        "playful": primary,
        "clever": secondary if secondary.detail != primary.detail else primary,
        "flirty": (
            tertiary
            if tertiary.detail not in {primary.detail, secondary.detail}
            else (secondary if secondary.detail != primary.detail else primary)
        ),
    }


def _is_verbatim_quote(text: str, hook: HookContext) -> bool:
    lower = text.lower().strip().strip('"').strip("'")
    detail = hook.detail.lower().strip()
    label = hook.label.lower().strip()

    if detail and len(detail) >= 12 and detail in lower:
        # Mostly her answer pasted back
        if len(lower) <= len(detail) * 1.35:
            return True
    if "don't hate me if i" in lower and "serious" in lower and "laugh" in lower:
        if lower.count("don't hate me") >= 1 and len(lower) < 90:
            return True
    if label and label in lower and detail in lower and len(lower) < len(detail) + 30:
        return True
    if hook.label.lower().startswith("this year") and detail.lower() in lower:
        if lower.startswith("this year"):
            return True
    return False


def _repeats_prompt_not_answer(text: str, hook: HookContext) -> bool:
    """Reject openers that cite the Hinge prompt title but not her answer."""
    label = hook.label.strip().lower().strip(".")
    detail = hook.detail.strip().lower()
    lower = text.lower()
    if len(label) < 12 or label not in lower:
        return False
    detail_tokens = [w for w in re.findall(r"[a-z0-9']+", detail) if len(w) > 3]
    if not detail_tokens:
        return False
    hits = sum(1 for w in detail_tokens if w in lower)
    return hits < min(1, len(detail_tokens))


def validate_opener(text: str, hook: HookContext) -> tuple[bool, str]:
    t = text.strip()
    lower = t.lower()
    if not t:
        return False, "empty opener"
    if len(t) < _MIN_LEN:
        return False, "too short to be specific"
    if len(t) > _MAX_LEN:
        return False, "too long for Hinge"
    if _START_BANNED.search(t):
        return False, "starts with Hey/Hi/Hello"
    if _is_verbatim_quote(t, hook):
        return False, "verbatim quote of her prompt/answer"
    if _repeats_prompt_not_answer(t, hook):
        return False, "repeats prompt title without her answer detail"
    for pat in INTERVIEW_PATTERNS:
        if re.search(pat, lower):
            return False, "interview-style or weak filler opener"
    for pat in GENERIC_PATTERNS:
        if re.search(pat, lower):
            return False, f"matches generic pattern: {pat}"
    for pat in APPEARANCE_PATTERNS:
        if re.search(pat, lower):
            return False, "appearance-focused opener"
    for phrase in banned_phrases():
        if not phrase:
            continue
        if phrase.lower() == "hey":
            continue
        if phrase.lower() in lower:
            return False, f"contains banned phrase: {phrase}"
    if hook.anchor_words:
        if not any(w in lower for w in hook.anchor_words):
            return False, f"does not reference hook ({', '.join(hook.anchor_words[:4])})"
    detail_l = hook.detail.lower()
    if ("bacchon" in lower or "baap" in lower) and "bacchon" not in detail_l and "baap" not in detail_l:
        return False, "opener references wrong profile (bacchon/baap mismatch)"
    return True, ""


def _fallback_is_grounded(hook: HookContext, text: str) -> bool:
    """Fallback only when it clearly references the detected hook."""
    if hook.hook_key == "generic":
        return False
    lower = text.lower()
    if not hook.anchor_words:
        return False
    hits = sum(1 for w in hook.anchor_words if w in lower)
    return hits >= min(2, max(1, len(hook.anchor_words) // 2))


def _fallback_opener(style: str, hook: HookContext) -> OpenerCandidate | None:
    if hook.hook_key == "life_partner":
        detail = hook.detail.lower()
        if "bacchon" not in detail and "baap" not in detail:
            return None
    text = _FALLBACK_OPENERS.get((style, hook.hook_key))
    if not text:
        text = _FALLBACK_OPENERS.get((style, "yapping"))
    if not text and hook.hook_key == "generic":
        detail = hook.detail.lower()
        if "bacchon" in detail or "baap" in detail:
            text = _FALLBACK_OPENERS.get((style, "life_partner"))
        elif "spontaneous" in detail:
            text = _FALLBACK_OPENERS.get((style, "spontaneous"))
        elif "perfume" in detail:
            text = _FALLBACK_OPENERS.get((style, "perfume"))
        elif "greek" in detail or "diss" in detail:
            text = _FALLBACK_OPENERS.get((style, "greek_philosophers"))
        elif "pythagorean" in detail:
            text = _FALLBACK_OPENERS.get((style, "pythagorean"))
        elif "pun" in detail:
            text = _FALLBACK_OPENERS.get((style, "pun_relay"))
        elif "niche" in detail or "nerdy" in detail:
            text = _FALLBACK_OPENERS.get((style, "yap_niche"))
        elif "homies" in detail:
            text = _FALLBACK_OPENERS.get((style, "homies"))
        elif "bob" in detail or "stuart" in detail:
            text = _FALLBACK_OPENERS.get((style, "minions"))
        elif "mountain" in detail:
            text = _FALLBACK_OPENERS.get((style, "mountains"))
        elif "cookie" in detail or "chocolate" in detail:
            text = _FALLBACK_OPENERS.get((style, "cookies"))
        elif "stoic" in detail:
            text = _FALLBACK_OPENERS.get((style, "stoic"))
        elif "nbhd" in detail:
            text = _FALLBACK_OPENERS.get((style, "nbhd"))
        elif "making things" in detail:
            text = _FALLBACK_OPENERS.get((style, "making_things"))
        elif "charlotte" in detail or "york" in detail:
            text = _FALLBACK_OPENERS.get((style, "charlotte_york"))
        elif "arguments" in detail:
            text = _FALLBACK_OPENERS.get((style, "family_arguments"))
        elif "overdressed" in detail:
            text = _FALLBACK_OPENERS.get((style, "overdressed"))
    if not text:
        return None
    if not _fallback_is_grounded(hook, text):
        return None
    valid, reason = validate_opener(text, hook)
    return OpenerCandidate(
        style=style,
        text=text,
        hook_used=hook.label,
        evidence=hook.evidence,
        valid=valid,
        rejection_reason=reason if not valid else "",
    )


def _single_opener_system() -> str:
    voice = resolve_voice(config.MESSAGE_VOICE)
    hints = natural_phrase_hints()
    hint_block = ""
    if hints:
        hint_block = "Aryan natural phrase energy (adapt, don't copy blindly):\n- " + "\n- ".join(hints[:6])
    return f"""Write ONE Hinge like-comment opener.

{personality_prompt_section()}

{voice}

{hint_block}

CRITICAL:
- STATEMENT with tease/ragebait-lite energy — NOT an interview question.
- Comment on her ANSWER detail, not the prompt question text.
- English / Hindi / Gujarati (romanized) — pick what fits her profile and the hook.
- Do NOT paste her prompt answer back.
- No appearance comments.

Respond with ONLY JSON:
{{"text": "opener here", "hook_used": "hook label", "evidence": "evidence used"}}"""


def _generate_single_opener(
    profile: ProfileAnalysis,
    style: str,
    hook: HookContext,
    *,
    retry_reason: str = "",
) -> tuple[OpenerCandidate, dict]:
    retry_note = ""
    if retry_reason:
        retry_note = (
            f"\nREJECTED because: {retry_reason}. "
            "Rewrite as a bold STATEMENT/tease — no Hey, no What's your, no quoting her answer."
        )
    user = f"""{_STYLE_GUIDE[style]}

Profile name: {profile.name}
Hook detail: {hook.detail}
Hook label: {hook.label}
Evidence: {hook.evidence}
Required anchor words: {', '.join(hook.anchor_words[:6])}
{retry_note}

Write one {style} opener. Boldness 7-8/10. Statement she wants to reply to."""

    data, usage = text_json(
        _single_opener_system(),
        user,
        num_predict=OPENERS_NUM_PREDICT,
        compact_user=user,
    )
    text = str(data.get("text", "")).strip()
    hook_used = str(data.get("hook_used") or hook.label)
    evidence = str(data.get("evidence") or hook.evidence)
    valid, reason = validate_opener(text, hook)
    return OpenerCandidate(
        style=style,
        text=text,
        hook_used=hook_used,
        evidence=evidence,
        valid=valid,
        rejection_reason=reason,
    ), usage


def _pick_recommended_opener(
    candidates: list[OpenerCandidate],
    profile: ProfileAnalysis,
) -> tuple[str, str]:
    """Prefer valid opener on the strongest cleaned prompt hook."""
    best = profile.best_hook()
    if best:
        best_detail = best.detail.lower()
        for c in candidates:
            if not c.valid:
                continue
            text_l = c.text.lower()
            if best_detail in text_l or any(
                w in text_l for w in best_detail.split() if len(w) > 4
            ):
                return c.style, f"Best hook: {best.detail[:80]}"
    for c in candidates:
        if c.valid:
            return c.style, f"Valid opener on hook: {c.hook_used}"
    return "", "No valid opener — edit manually or skip"


def generate_openers(
    profile: ProfileAnalysis,
    compatibility: CompatibilityResult,
) -> tuple[list[OpenerCandidate], str, str]:
    if compatibility.decision != "like":
        return [], "", ""

    hook_pool = rank_hooks_for_openers(profile)
    assignments = _assign_hooks(hook_pool)

    print("  [openers] selected hooks:")
    for style in _STYLES:
        h = assignments[style]
        print(f"    {style}: {h.detail} — {h.evidence[:70]}{'…' if len(h.evidence) > 70 else ''}")

    candidates: list[OpenerCandidate] = []
    total_usage = {"input_tokens": 0, "output_tokens": 0}

    for style in _STYLES:
        hook = assignments[style]
        fallback = _fallback_opener(style, hook)
        if (
            getattr(config, "OPENER_FALLBACK_FIRST", True)
            and fallback
            and fallback.valid
            and _fallback_is_grounded(hook, fallback.text)
        ):
            print(f"  [openers] {style} using voice fallback")
            candidates.append(fallback)
            continue

        print(f"  [openers] generating {style}…")
        candidate, usage = _generate_single_opener(profile, style, hook)
        total_usage["input_tokens"] += usage.get("input_tokens", 0)
        total_usage["output_tokens"] += usage.get("output_tokens", 0)
        if not candidate.valid:
            print(f"  [openers] {style} invalid ({candidate.rejection_reason}) — regenerating")
            candidate, usage2 = _generate_single_opener(
                profile, style, hook, retry_reason=candidate.rejection_reason
            )
            total_usage["input_tokens"] += usage2.get("input_tokens", 0)
            total_usage["output_tokens"] += usage2.get("output_tokens", 0)
        if not candidate.valid:
            print(f"  [openers] {style} still invalid — using voice-matched fallback")
            fallback = _fallback_opener(style, hook)
            if fallback and fallback.valid:
                candidate = fallback
            elif not candidate.valid:
                print(f"  [openers] {style} fallback also failed: {candidate.rejection_reason}")
        candidates.append(candidate)

    recommended_style, recommended_reason = _pick_recommended_opener(candidates, profile)

    compatibility.usage = _merge_usage(compatibility.usage, total_usage)
    return candidates, recommended_style, recommended_reason


def _merge_usage(a: dict, b: dict) -> dict:
    return {
        "input_tokens": a.get("input_tokens", 0) + b.get("input_tokens", 0),
        "output_tokens": a.get("output_tokens", 0) + b.get("output_tokens", 0),
    }


_validate_opener = validate_opener
