export type VideoCategory =
  | "Product"
  | "Architecture"
  | "Culture"
  | "Onboarding"
  | "AI Generated";

export type VideoKind = "clip" | "generated";

export type StoryboardScene = {
  title: string;
  visual: string;
  narration: string;
  caption: string;
};

export type ReactionCounts = {
  useful: number;
  saved: number;
  questions: number;
};

export type CommentItem = {
  id: string;
  author: string;
  text: string;
  createdAt: string;
};

export type ViewerState = {
  liked?: boolean;
  saved?: boolean;
};

export type VideoItem = {
  id: string;
  title: string;
  team: string;
  author: string;
  category: VideoCategory;
  description: string;
  tags: string[];
  duration: string;
  createdAt: string;
  kind: VideoKind;
  accent: string;
  reactions: ReactionCounts;
  comments?: CommentItem[];
  viewerState?: ViewerState;
  script?: string;
  sourceText?: string;
  scenes?: StoryboardScene[];
};

export type GeneratedExplainer = {
  title: string;
  summary: string;
  duration: string;
  tags: string[];
  script: string;
  scenes: StoryboardScene[];
};
