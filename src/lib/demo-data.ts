import type { VideoItem } from "./types";

export const categoryOptions = [
  "Product",
  "Architecture",
  "Culture",
  "Onboarding",
  "AI Generated",
] as const;

export const accentOptions = [
  "from-blue-500 via-indigo-500 to-violet-600",
  "from-emerald-500 via-teal-500 to-cyan-600",
  "from-orange-500 via-rose-500 to-pink-600",
  "from-slate-700 via-slate-900 to-black",
  "from-amber-400 via-orange-500 to-red-600",
];

export const seedVideos: VideoItem[] = [
  {
    id: "seed-route-to-tokenization",
    title: "Route to Tokenization in 90 seconds",
    team: "Payments Platform",
    author: "Ananya from Platform",
    category: "Product",
    description:
      "A byte-sized walkthrough of how a card transaction becomes a reusable network token and where risk checks sit in the flow.",
    tags: ["cards", "tokenization", "payments"],
    duration: "1:28",
    createdAt: "Today",
    kind: "clip",
    accent: accentOptions[0],
    reactions: { useful: 124, saved: 38, questions: 6 },
    comments: [
      {
        id: "comment-tokenization-1",
        author: "Riya",
        text: "This makes the vaulting boundary much easier to explain.",
        createdAt: "12m ago",
      },
    ],
    viewerState: {},
    scenes: [
      {
        title: "The customer moment",
        visual: "Checkout screen with card saved securely",
        narration:
          "The user sees one saved-card action, but the platform coordinates card network, issuer, and internal vaulting layers.",
        caption: "Saved card ≠ stored PAN",
      },
      {
        title: "Network token exchange",
        visual: "Issuer, network, and Razorpay nodes exchanging a token",
        narration:
          "The original card credential is exchanged for a token that can be scoped, rotated, and monitored independently.",
        caption: "Scoped network token",
      },
    ],
  },
  {
    id: "seed-new-joiner-map",
    title: "New joiner map: who owns what?",
    team: "People Experience",
    author: "Razorpay Culture Guild",
    category: "Onboarding",
    description:
      "A fast tour of product groups, common Slack channels, and where to find source-of-truth documents in week one.",
    tags: ["onboarding", "teams", "culture"],
    duration: "2:05",
    createdAt: "Yesterday",
    kind: "clip",
    accent: accentOptions[1],
    reactions: { useful: 211, saved: 94, questions: 12 },
    comments: [
      {
        id: "comment-onboarding-1",
        author: "Kabir",
        text: "Can we pin this for every new cohort?",
        createdAt: "1h ago",
      },
    ],
    viewerState: {},
    scenes: [
      {
        title: "First week map",
        visual: "Org map with product, engineering, support, and ops clusters",
        narration:
          "A new joiner needs a map of teams before they need a hundred links. Start with ownership, then route to docs.",
        caption: "Start with ownership",
      },
    ],
  },
  {
    id: "seed-switch-architecture",
    title: "UPI switch architecture: current vs next",
    team: "UPI Core",
    author: "Architecture Review Bot",
    category: "Architecture",
    description:
      "A generated-style explainer showing how traffic, readiness checks, and dependency health fit together in an API-pod rollout.",
    tags: ["architecture", "upi", "readiness"],
    duration: "1:54",
    createdAt: "Mon",
    kind: "generated",
    accent: accentOptions[3],
    reactions: { useful: 87, saved: 41, questions: 9 },
    comments: [
      {
        id: "comment-switch-1",
        author: "Devika",
        text: "The alive vs ready split finally clicked.",
        createdAt: "2h ago",
      },
    ],
    viewerState: {},
    script:
      "In the current flow, API pods accept traffic before every critical dependency is proven healthy. The proposed rollout adds readiness gates so Kubernetes routes only to pods that can serve payment paths safely.",
    scenes: [
      {
        title: "Before",
        visual: "Load balancer sending traffic to pods with unknown dependency health",
        narration:
          "Today the pod may be alive while downstream readiness is still uncertain.",
        caption: "Alive is not always ready",
      },
      {
        title: "After",
        visual: "Readiness gate checking database, Redis, Kafka, and gRPC clients",
        narration:
          "The new readiness gate protects customer traffic by checking the dependency set before the pod joins service.",
        caption: "Route only to ready pods",
      },
    ],
  },
];
