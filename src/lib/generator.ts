import type { GeneratedExplainer, StoryboardScene } from "./types";

const stopWords = new Set([
  "about",
  "after",
  "again",
  "against",
  "also",
  "and",
  "are",
  "because",
  "been",
  "before",
  "being",
  "between",
  "but",
  "can",
  "could",
  "current",
  "during",
  "each",
  "from",
  "have",
  "into",
  "more",
  "need",
  "needs",
  "only",
  "other",
  "over",
  "than",
  "that",
  "the",
  "their",
  "then",
  "there",
  "this",
  "through",
  "will",
  "with",
  "within",
  "without",
]);

function cleanText(value: string) {
  return value.replace(/\s+/g, " ").trim();
}

function titleCase(value: string) {
  return value
    .split(" ")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(" ");
}

function splitSentences(input: string) {
  const cleaned = cleanText(input);

  if (!cleaned) {
    return [];
  }

  return cleaned
    .split(/(?<=[.!?])\s+/)
    .map((sentence) => sentence.trim())
    .filter(Boolean);
}

function extractKeywords(input: string) {
  const counts = new Map<string, number>();
  const words = input.toLowerCase().match(/[a-z][a-z0-9-]{2,}/g) ?? [];

  for (const word of words) {
    if (stopWords.has(word)) {
      continue;
    }

    counts.set(word, (counts.get(word) ?? 0) + 1);
  }

  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, 5)
    .map(([word]) => word);
}

function buildTitle(input: string, keywords: string[]) {
  const firstLine = input
    .split("\n")
    .map((line) => line.trim())
    .find((line) => line.length > 8 && line.length < 84);

  if (firstLine) {
    return firstLine.replace(/^#+\s*/, "").replace(/[.:;-]$/, "");
  }

  if (keywords.length > 0) {
    return `${titleCase(keywords.slice(0, 3).join(" "))} explainer`;
  }

  return "Internal knowledge explainer";
}

function buildScene(index: number, sentence: string, keyword: string): StoryboardScene {
  const scenePatterns = [
    {
      title: "Hook",
      visual: "A fast before/after split-screen that shows the pain in one glance",
      caption: "Why this matters now",
    },
    {
      title: "System map",
      visual: "A simple node diagram connecting people, systems, and decisions",
      caption: "Map the moving parts",
    },
    {
      title: "Change moment",
      visual: "Animated arrows showing the current workflow becoming the proposed workflow",
      caption: "From current to proposed",
    },
    {
      title: "Proof",
      visual: "A checklist overlay showing what users can now do faster or safer",
      caption: "What viewers can trust",
    },
    {
      title: "Call to action",
      visual: "A final card with owner, next step, and where to read more",
      caption: "Watch, react, follow up",
    },
  ];
  const pattern = scenePatterns[index % scenePatterns.length];

  return {
    title: `${index + 1}. ${pattern.title}${keyword ? `: ${titleCase(keyword)}` : ""}`,
    visual: pattern.visual,
    narration: sentence.replace(/[.!?]$/, "."),
    caption: pattern.caption,
  };
}

export function generateExplainer(input: string): GeneratedExplainer {
  const cleaned = cleanText(input);
  const fallback =
    "Explain the problem, show the current workflow, introduce the proposed solution, and end with the viewer takeaways.";
  const source = cleaned || fallback;
  const sentences = splitSentences(source);
  const keywords = extractKeywords(source);
  const selectedSentences = sentences.length >= 3 ? sentences.slice(0, 5) : [...sentences, fallback].slice(0, 4);
  const scenes = selectedSentences.map((sentence, index) =>
    buildScene(index, sentence, keywords[index] ?? "")
  );
  const title = buildTitle(input, keywords);
  const summary =
    sentences[0]?.replace(/[.!?]$/, ".") ??
    "A short generated explainer that turns dense internal knowledge into a watchable learning story.";
  const script = [
    `Open with the question: why should a Razorpay employee care about ${keywords[0] ?? "this topic"}?`,
    ...scenes.map((scene) => scene.narration),
    "Close by inviting viewers to save the clip, ask questions, and open the source AIDoc when they need implementation detail.",
  ].join("\n\n");

  return {
    title,
    summary,
    duration: `${Math.max(1, Math.ceil(scenes.length * 0.35))}:${String(
      Math.min(55, scenes.length * 11)
    ).padStart(2, "0")}`,
    tags: Array.from(new Set(["AI Generated", "AIDoc", ...keywords.slice(0, 3)])),
    script,
    scenes,
  };
}
