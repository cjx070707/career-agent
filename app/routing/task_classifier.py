"""Keyword-based task-family classifier (no LLM — pure regex/token match).

TaskFamily tags what kind of career task the user is asking about.
Used by the memory context budget to prioritise relevant conversation history.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Optional


class TaskFamily(str, Enum):
    JOB_SEARCH = "job_search"
    INTERVIEW = "interview"
    APPLICATION = "application"
    RESUME = "resume"
    GOAL = "goal"
    GENERAL = "general"


# Ordered list of (family, patterns).  Each matched pattern adds 1 point;
# the family with the highest score wins.  Ties fall through to the next
# family in declaration order, so specificity matters.
_RULES: list[tuple[TaskFamily, list[str]]] = [
    (
        TaskFamily.JOB_SEARCH,
        [
            r"找.{0,6}(工作|岗位|职位|实习|offer|job)",
            r"(搜|查找|推荐|有什么|有没有).{0,6}(岗位|职位|工作|job)",
            r"\b(search.?job|job.?search)\b",
            r"(python|java|golang|rust|react|vue|前端|后端|backend|frontend|全栈|算法|data.?engineer|ml.?engineer)",
            r"(实习|intern(ship)?)",
            r"(sydney|melbourne|remote|混合办公|onsite)\s*(岗位|job|role|position)",
        ],
    ),
    (
        TaskFamily.INTERVIEW,
        [
            r"面试",
            r"\b(interview|mock.?interview|面经|笔试)\b",
            r"(system.?design|coding.?round|behavioral|行为面试)",
            r"(没过|过了|拒了|rejected|oa|online.?assessment)",
            r"(interview.?feedback|面试.?反馈|面试.?结果)",
            r"怎么准备.{0,8}面试",
        ],
    ),
    (
        TaskFamily.APPLICATION,
        [
            r"(投(递|了|过)|申请)(简历|岗位|职位)?",
            r"\b(application|apply|applied)\b",
            r"(投档|投了多少|投了哪些)",
            r"(申请.?状态|application.?status)",
            r"最近.{0,4}投",
        ],
    ),
    (
        TaskFamily.RESUME,
        [
            r"简历",
            r"\b(resume|cv)\b",
            r"(gap.?分析|gap.?analysis|差距分析)",
            r"(简历.?(优化|分析|改|写|修|怎么样))",
            r"(技能.?差距|skills?.?gap)",
            r"(上传|解析).{0,4}简历",
        ],
    ),
    (
        TaskFamily.GOAL,
        [
            r"(设定|制定|更新|完成).{0,4}(目标|goal)",
            r"\b(goal|deadline|目标|计划|规划|里程碑)\b",
            r"(进展|progress|log.?progress)",
            r"(上次说|之前说).{0,8}(做|完成|计划)",
        ],
    ),
]

_COMPILED: list[tuple[TaskFamily, list[re.Pattern[str]]]] = [
    (family, [re.compile(p, re.IGNORECASE) for p in patterns])
    for family, patterns in _RULES
]


def classify(text: str) -> TaskFamily:
    """Return the dominant TaskFamily for *text*.

    Scores each family by counting matched patterns; returns GENERAL when
    no family scores above zero.
    """
    scores: dict[TaskFamily, int] = {f: 0 for f in TaskFamily}
    for family, compiled_patterns in _COMPILED:
        for pattern in compiled_patterns:
            if pattern.search(text):
                scores[family] += 1

    best_family = max(scores, key=lambda f: scores[f])
    return best_family if scores[best_family] > 0 else TaskFamily.GENERAL


def score_turn(text: str, family: TaskFamily) -> int:
    """Return how many patterns from *family* match *text* (0 = irrelevant)."""
    if family is TaskFamily.GENERAL:
        return 1  # GENERAL turns are always considered relevant
    for fam, compiled_patterns in _COMPILED:
        if fam is family:
            return sum(1 for p in compiled_patterns if p.search(text))
    return 0
