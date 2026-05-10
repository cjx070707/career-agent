import { FileSearch, ListChecks, MessageSquareText, Sparkles } from "lucide-react";

export const queryStarters = [
  {
    label: "Find jobs",
    prompt: "帮我找一些 Python backend 岗位",
    icon: FileSearch,
  },
  {
    label: "Career diagnosis",
    prompt: "结合我的投递和面试反馈，我下一步该准备什么？",
    icon: Sparkles,
  },
  {
    label: "Applications",
    prompt: "我最近投了哪些岗位？",
    icon: ListChecks,
  },
  {
    label: "Interviews",
    prompt: "我最近面试反馈怎么样？",
    icon: MessageSquareText,
  },
];
