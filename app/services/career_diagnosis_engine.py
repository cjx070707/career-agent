from typing import Dict, List, Union


class CareerDiagnosisEngine:
    BOTTLENECK_PRIORITY = {
        "skill_gap": 6,
        "interview_performance": 5,
        "job_targeting": 4,
        "resume_positioning": 3,
        "application_volume": 2,
        "insufficient_evidence": 1,
    }

    CONFIDENCE_DEFAULTS = {
        "insufficient_evidence": 0.3,
        "application_volume": 0.5,
        "resume_positioning": 0.65,
        "job_targeting": 0.7,
        "interview_performance": 0.75,
        "skill_gap": 0.82,
    }

    PRIORITY_LABELS = {
        "insufficient_evidence": "low",
        "application_volume": "medium",
        "resume_positioning": "high",
        "job_targeting": "high",
        "interview_performance": "high",
        "skill_gap": "high",
    }

    SKILL_GAP_PATTERNS = (
        "sql",
        "coding",
        "system design",
        "technical depth",
        "project depth",
        "communication",
        "python",
        "data structure",
        "ml",
        "backend",
    )
    NEGATIVE_FEEDBACK_PATTERNS = (
        "need",
        "lack",
        "weak",
        "insufficient",
        "gap",
        "不足",
        "欠缺",
        "薄弱",
        "不够",
    )
    TARGETING_PATTERNS = (
        "low alignment",
        "not relevant",
        "too broad",
        "方向太散",
        "不匹配",
        "岗位跨度大",
    )
    EARLY_STATUSES = {"applied", "submitted"}
    ADVANCED_STATUSES = {"interview", "interviewing", "offered", "offer"}

    def diagnose(
        self,
        profile: Dict[str, object],
        applications: List[Dict[str, Union[int, str]]],
        interviews: List[Dict[str, Union[int, str]]],
        feedback_highlights: List[str],
    ) -> Dict[str, object]:
        candidates = []
        role = str(profile.get("target_role_preference", "") or "").strip()
        normalized_feedback = [
            str(item).strip().lower()
            for item in feedback_highlights
            if str(item).strip()
        ]
        normalized_interview_feedback = [
            str(item.get("feedback", "")).strip().lower()
            for item in interviews
            if str(item.get("feedback", "")).strip()
        ]
        all_feedback = normalized_feedback + normalized_interview_feedback

        skill_signals = self._find_skill_gap_signals(all_feedback)
        if skill_signals:
            evidence = [
                {
                    "source": "feedback",
                    "signal": "skill_gap_feedback",
                    "detail": f"feedback mentions {', '.join(skill_signals[:3])}",
                }
            ]
            candidates.append(
                self._build_result(
                    bottleneck_type="skill_gap",
                    diagnosis_summary=(
                        "反馈显示存在明确技能短板，优先补齐关键技术能力再进入下一轮投递。"
                    ),
                    evidence=evidence,
                    recommended_actions=[
                        "围绕反馈中的核心技能短板制定两周训练清单并打卡。",
                        "补充可展示该技能的项目或题解材料。",
                        "下次面试前用同类题目进行一次模拟复盘。",
                    ],
                )
            )

        rejected_interviews = [
            item
            for item in interviews
            if str(item.get("result", "")).strip().lower() == "rejected"
        ]
        has_negative_feedback = any(
            any(pattern in text for pattern in self.NEGATIVE_FEEDBACK_PATTERNS)
            for text in all_feedback
        )
        if rejected_interviews or has_negative_feedback:
            evidence = []
            if rejected_interviews:
                evidence.append(
                    {
                        "source": "interviews",
                        "signal": "rejected_interviews",
                        "detail": f"found {len(rejected_interviews)} rejected interview(s)",
                    }
                )
            if has_negative_feedback:
                evidence.append(
                    {
                        "source": "feedback",
                        "signal": "negative_feedback",
                        "detail": "feedback contains explicit weakness signals",
                    }
                )
            candidates.append(
                self._build_result(
                    bottleneck_type="interview_performance",
                    diagnosis_summary=(
                        "面试阶段存在明显损失，需要重点复盘答题结构与关键能力表达。"
                    ),
                    evidence=evidence,
                    recommended_actions=[
                        "按最近被拒轮次整理问题清单并复盘失分点。",
                        "补充 STAR/项目深挖回答模板并完成一次模拟面试。",
                        "把反馈中的高频薄弱项转成每日练习任务。",
                    ],
                )
            )

        targeting_hits = self._find_targeting_signals(applications)
        if targeting_hits:
            candidates.append(
                self._build_result(
                    bottleneck_type="job_targeting",
                    diagnosis_summary=(
                        "投递目标存在方向或相关性偏差，建议先收敛目标岗位再继续投递。"
                    ),
                    evidence=[
                        {
                            "source": "applications",
                            "signal": "explicit_targeting_mismatch",
                            "detail": targeting_hits[0],
                        }
                    ],
                    recommended_actions=[
                        "先收敛到 1-2 类目标岗位并定义必备关键词。",
                        "投递前用岗位要求清单做相关性打分。",
                        "暂停低相关岗位，优先高匹配岗位批量投递。",
                    ],
                )
            )

        if applications:
            statuses = [
                str(item.get("status", "")).strip().lower()
                for item in applications
                if str(item.get("status", "")).strip()
            ]
            early_count = sum(1 for status in statuses if status in self.EARLY_STATUSES)
            has_advanced = any(status in self.ADVANCED_STATUSES for status in statuses)
            if statuses and early_count >= max(1, int(len(statuses) * 0.6)) and not has_advanced and not interviews:
                candidates.append(
                    self._build_result(
                        bottleneck_type="resume_positioning",
                        diagnosis_summary=(
                            "当前投递主要停留在早期阶段，面试转化偏弱，简历定位与岗位表达需要优化。"
                        ),
                        evidence=[
                            {
                                "source": "applications",
                                "signal": "funnel_stuck_early",
                                "detail": (
                                    f"{early_count}/{len(statuses)} applications are applied/submitted without interview progression"
                                ),
                            }
                        ],
                        recommended_actions=[
                            "针对目标岗位重写简历抬头与项目要点，突出关键词命中。",
                            "为每次投递附上定制化岗位匹配要点。",
                            "优先复投高度匹配岗位，观察面试转化变化。",
                        ],
                    )
                )

        if role and not applications and not interviews:
            candidates.append(
                self._build_result(
                    bottleneck_type="application_volume",
                    diagnosis_summary=(
                        "目标岗位已明确，但样本不足，暂不应过早判断简历或面试能力问题。"
                    ),
                    evidence=[
                        {
                            "source": "profile",
                            "signal": "target_role_defined",
                            "detail": f"target role is set to {role}",
                        },
                        {
                            "source": "applications",
                            "signal": "no_records",
                            "detail": "no applications or interviews found",
                        },
                    ],
                    recommended_actions=[
                        "先在两周内建立可追踪投递样本量。",
                        "记录每次投递岗位、状态与反馈，形成漏斗基线。",
                        "样本达到后再判断是定位问题还是面试问题。",
                    ],
                )
            )

        if not candidates:
            candidates.append(
                self._build_result(
                    bottleneck_type="insufficient_evidence",
                    diagnosis_summary=(
                        "当前证据不足，无法做高置信诊断，先补齐目标岗位与求职过程数据。"
                    ),
                    evidence=[
                        {
                            "source": "profile",
                            "signal": "missing_role_or_records",
                            "detail": "missing target role and/or usable application/interview evidence",
                        }
                    ],
                    recommended_actions=[
                        "先明确目标岗位方向。",
                        "提供最新简历内容。",
                        "补充最近投递和面试反馈记录。",
                    ],
                )
            )

        final = max(
            candidates,
            key=lambda item: self.BOTTLENECK_PRIORITY[str(item["bottleneck_type"])],
        )
        final["confidence"] = self._bound_confidence(
            bottleneck_type=str(final["bottleneck_type"]),
            confidence=float(final["confidence"]),
            evidence=final["evidence"],
        )
        return final

    def _find_skill_gap_signals(self, feedback_list: List[str]) -> List[str]:
        signals = []
        for text in feedback_list:
            for keyword in self.SKILL_GAP_PATTERNS:
                if keyword in text:
                    signals.append(keyword)
        deduped = []
        seen = set()
        for signal in signals:
            if signal not in seen:
                deduped.append(signal)
                seen.add(signal)
        return deduped

    def _find_targeting_signals(
        self,
        applications: List[Dict[str, Union[int, str]]],
    ) -> List[str]:
        hits = []
        for item in applications:
            text_parts = [
                str(item.get("status", "")).strip().lower(),
                str(item.get("note", "")).strip().lower(),
                str(item.get("job_title", "")).strip().lower(),
            ]
            text = " ".join(part for part in text_parts if part)
            for marker in self.TARGETING_PATTERNS:
                if marker in text:
                    hits.append(
                        f"application '{item.get('company', '')}-{item.get('job_title', '')}' includes '{marker}'"
                    )
                    break
        return hits

    def _build_result(
        self,
        *,
        bottleneck_type: str,
        diagnosis_summary: str,
        evidence: List[Dict[str, str]],
        recommended_actions: List[str],
    ) -> Dict[str, object]:
        return {
            "bottleneck_type": bottleneck_type,
            "diagnosis_summary": diagnosis_summary,
            "confidence": self.CONFIDENCE_DEFAULTS[bottleneck_type],
            "priority": self.PRIORITY_LABELS[bottleneck_type],
            "evidence": evidence,
            "recommended_actions": recommended_actions[:3],
        }

    def _bound_confidence(
        self,
        *,
        bottleneck_type: str,
        confidence: float,
        evidence: List[Dict[str, str]],
    ) -> float:
        has_feedback_evidence = any(item.get("source") == "feedback" for item in evidence)
        bounded = max(0.2, min(confidence, 0.9))
        if bounded >= 0.8 and not has_feedback_evidence:
            bounded = 0.75
        if bottleneck_type == "insufficient_evidence":
            bounded = min(bounded, 0.4)
        return round(bounded, 2)
