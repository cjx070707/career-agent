DEFAULT_PLANNER_EVAL_CASES = [
    {
        "name": "job_search_with_profile",
        "input": {
            "message": "帮我找一些岗位",
            "memory_context": ["我们刚刚聊过后端实习方向"],
            "profile": {
                "target_role_preference": "backend",
                "skill_keywords": ["python", "fastapi"],
            },
            "available_tools": ["search_jobs", "match_resume_to_jobs"],
            "user_state": {"has_candidate": True, "has_resume": True},
        },
        "expected": {
            "task_type": "job_search",
            "steps": ["search_jobs"],
            "needs_more_context": False,
            "missing_context": [],
            "follow_up_question": None,
        },
    },
    {
        "name": "job_match_missing_resume",
        "input": {
            "message": "我适合投哪些岗位",
            "memory_context": [],
            "profile": {},
            "available_tools": ["match_resume_to_jobs"],
            "user_state": {"has_candidate": True, "has_resume": False},
        },
        "expected": {
            "task_type": "job_match",
            "steps": [],
            "needs_more_context": True,
            "missing_context": ["resume"],
            "follow_up_question": "请先提供简历",
        },
    },
    {
        "name": "job_match_missing_tools",
        "input": {
            "message": "结合我的情况推荐适合投的岗位",
            "memory_context": [],
            "profile": {},
            "available_tools": ["get_candidate_profile", "search_jobs"],
            "user_state": {"has_candidate": True, "has_resume": True},
        },
        "expected": {
            "task_type": "job_match_planning",
            "steps": ["get_candidate_profile", "search_jobs"],
            "needs_more_context": True,
            "missing_context": ["tooling"],
            "follow_up_question": None,
        },
    },
    {
        "name": "multi_step_recommendation",
        "input": {
            "message": "结合我的情况推荐适合投的岗位",
            "memory_context": ["最近重点关注后端方向"],
            "profile": {
                "target_role_preference": "backend",
                "skill_keywords": ["python", "fastapi"],
            },
            "available_tools": [
                "get_candidate_profile",
                "get_resume_by_id",
                "search_jobs",
                "match_resume_to_jobs",
            ],
            "user_state": {"has_candidate": True, "has_resume": True},
        },
        "expected": {
            "task_type": "job_match_planning",
            "steps": [
                "get_candidate_profile",
                "get_resume_by_id",
                "search_jobs",
                "match_resume_to_jobs",
            ],
            "needs_more_context": False,
            "missing_context": [],
            "follow_up_question": None,
        },
    },
    {
        "name": "candidate_profile_missing_candidate",
        "input": {
            "message": "看看我的资料",
            "memory_context": [],
            "profile": {},
            "available_tools": ["get_candidate_profile"],
            "user_state": {"has_candidate": False, "has_resume": False},
        },
        "expected": {
            "task_type": "candidate_profile",
            "steps": [],
            "needs_more_context": True,
            "missing_context": ["candidate_profile"],
            "follow_up_question": "请先补充你的基本信息",
        },
    },
]
