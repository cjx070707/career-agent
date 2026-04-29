from dataclasses import dataclass

from app.routing.message_normalizer import NormalizedMessage, normalize_message

_JOB_SEARCH_ACTION_KEYWORDS_ZH = ("找", "搜", "推荐", "看看有没有")
_JOB_SEARCH_OBJECT_KEYWORDS_ZH = ("岗位", "职位", "招聘", "实习", "岗")
_JOB_SEARCH_ACTION_KEYWORDS_EN = ("find", "search", "recommend", "look for")
_JOB_SEARCH_OBJECT_KEYWORDS_EN = ("job", "jobs", "role", "position", "internship")
_COMPOUND_MATCH_MARKERS = ("简历", "匹配度", "match my resume", "resume match")
_GREETING_MESSAGES = {"hi", "hello", "hey", "你好", "您好", "嗨"}
_GREETING_PHRASES = ("nihao", "ni hao")
_THIRD_PARTY_MARKERS = ("我朋友", "my friend", "室友", "同学")
_RESUME_MARKERS = ("简历", "resume", "cv")
_RESUME_SUMMARY_MARKERS = ("总结", "概括", "亮点", "summary", "summarize", "highlight")
_RESUME_REVIEW_MARKERS = (
    "我的简历是怎样的",
    "我的简历怎么样",
    "帮我看看我的简历",
    "评价一下我的简历",
    "看一下我的 resume",
    "how is my resume",
    "review my cv",
)
_JOB_FIT_MARKERS = (
    "适不适合我",
    "适合我吗",
    "fit for me",
    "am i a fit",
    "匹配吗",
    "匹配度",
    "能投吗",
    "值得投吗",
    "这个 jd",
    "这个职位",
    "这个岗位",
    "compare this job with my resume",
    "match my resume",
)
_JOB_DISCOVERY_FOR_ME_MARKERS = (
    "有什么适合我的岗位",
    "有什么适合我的职位",
    "有什么我能投的岗位",
    "有什么我能投的职位",
    "有哪些适合我的岗位",
    "有哪些适合我的职位",
    "what jobs fit me",
    "what roles fit me",
    "what jobs are suitable for me",
)
_CAREER_DIAGNOSIS_MARKERS = (
    "求职画像",
    "求职状态",
    "最近问题",
    "暴露",
    "career profile",
    "career status",
    "weakness",
    "pattern",
    "职业方向",
    "职业规划",
)
_NEXT_STEP_MARKERS = (
    "下一步",
    "接下来",
    "怎么办",
    "该做什么",
    "该干嘛",
    "怎么准备",
    "next step",
    "what should i do",
)
_CAREER_CONTEXT_MARKERS = (
    "投递",
    "申请",
    "面试",
    "反馈",
    "职业方向",
    "职业规划",
    "准备",
    "application",
    "interview",
    "career direction",
)
_APPLICATION_MARKERS = ("投递", "申请", "投了", "申请了", "application", "applications", "applied")
_HISTORY_MARKERS = ("最近", "记录", "状态", "进展", "history", "哪些")
_INTERVIEW_MARKERS = ("面试", "interview")
_INTERVIEW_PREP_MARKERS = ("准备", "prepare", "prep", "plan")
_INTERVIEW_HISTORY_MARKERS = ("最近", "记录", "反馈", "进展", "history", "哪些", "结果")
_INTERVIEW_FEEDBACK_MARKERS = ("feedback", "复盘", "笔试", "hr 面", "hr面")
_CAPABILITY_HELP_MARKERS = (
    "你到底有什么用啊",
    "你能做什么",
    "你有什么用",
    "help",
    "what can you do",
)
_RESUME_PRESENCE_MARKERS = (
    "我的简历你有吗",
    "你有我的简历吗",
    "我上传过简历吗",
    "do you have my resume",
    "have you got my cv",
)


def _has_any(text: str, lowered: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text or marker in lowered for marker in markers)


@dataclass(frozen=True)
class IntentSignals:
    is_greeting: bool
    has_capability_help: bool
    is_third_party: bool
    has_resume_presence_query: bool
    has_resume_summary: bool
    has_job_search: bool
    has_compound_match: bool
    has_job_fit: bool
    has_career_diagnosis: bool
    has_career_next_step: bool
    has_general_next_step: bool
    has_interview_prep: bool
    has_application_history: bool
    has_interview_history: bool
    has_interview_feedback_history: bool
    has_profile_query: bool
    has_simple_job_match: bool
    has_recommend_match: bool


def collect_intent_signals(message: str, lowered_message: str, stripped_message: str) -> IntentSignals:
    normalized: NormalizedMessage = normalize_message(message)
    normalized_stripped = normalized.collapsed
    lowered_message = normalized.lowered
    stripped_message = normalized.stripped
    has_job_search_zh = any(kw in message for kw in _JOB_SEARCH_ACTION_KEYWORDS_ZH) and any(
        kw in message for kw in _JOB_SEARCH_OBJECT_KEYWORDS_ZH
    )
    has_job_search_en = any(kw in lowered_message for kw in _JOB_SEARCH_ACTION_KEYWORDS_EN) and any(
        kw in lowered_message for kw in _JOB_SEARCH_OBJECT_KEYWORDS_EN
    )
    has_job_search = has_job_search_zh or has_job_search_en

    has_resume_signal = _has_any(message, lowered_message, _RESUME_MARKERS)
    has_summary_signal = _has_any(message, lowered_message, _RESUME_SUMMARY_MARKERS)
    has_review_signal = _has_any(message, lowered_message, _RESUME_REVIEW_MARKERS)
    has_interview_signal = _has_any(message, lowered_message, _INTERVIEW_MARKERS)
    has_interview_history_signal = _has_any(message, lowered_message, _INTERVIEW_HISTORY_MARKERS)

    has_next_step = _has_any(message, lowered_message, _NEXT_STEP_MARKERS)
    has_career_context = _has_any(message, lowered_message, _CAREER_CONTEXT_MARKERS)
    has_application = _has_any(message, lowered_message, _APPLICATION_MARKERS)
    has_history = _has_any(message, lowered_message, _HISTORY_MARKERS)

    return IntentSignals(
        is_greeting=(
            stripped_message.lower() in _GREETING_MESSAGES
            or any(phrase.replace(" ", "") == normalized_stripped for phrase in _GREETING_PHRASES)
        ),
        has_capability_help=_has_any(message, lowered_message, _CAPABILITY_HELP_MARKERS),
        is_third_party=_has_any(message, lowered_message, _THIRD_PARTY_MARKERS),
        has_resume_presence_query=_has_any(message, lowered_message, _RESUME_PRESENCE_MARKERS),
        has_resume_summary=has_resume_signal and (has_summary_signal or has_review_signal),
        has_job_search=has_job_search,
        has_compound_match=_has_any(message, lowered_message, _COMPOUND_MATCH_MARKERS),
        has_job_fit=_has_any(message, lowered_message, _JOB_FIT_MARKERS),
        has_career_diagnosis=_has_any(message, lowered_message, _CAREER_DIAGNOSIS_MARKERS),
        has_career_next_step=has_next_step and has_career_context,
        has_general_next_step=has_next_step,
        has_interview_prep=(
            has_interview_signal
            and _has_any(message, lowered_message, _INTERVIEW_PREP_MARKERS)
            and not has_interview_history_signal
        ),
        has_application_history=has_application and has_history,
        has_interview_history=has_interview_signal and has_interview_history_signal,
        has_interview_feedback_history=(
            _has_any(message, lowered_message, _INTERVIEW_FEEDBACK_MARKERS) and has_interview_history_signal
        ),
        has_profile_query=_has_any(message, lowered_message, ("资料", "画像", "我是谁")),
        has_simple_job_match=_has_any(
            message,
            lowered_message,
            ("适合投", "适合哪些岗位", *_JOB_DISCOVERY_FOR_ME_MARKERS),
        ),
        has_recommend_match=_has_any(message, lowered_message, ("结合我的情况", "推荐适合投", "推荐适合")),
    )
