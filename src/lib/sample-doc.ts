export const sampleAidocTitle = "Payment Routing Readiness Explainer";

export const sampleAidoc = `# AIDoc: Payment Routing Readiness Explainer

## 1. Context

Razorpay payment APIs receive customer traffic through Kubernetes services. A pod can be alive at the process level while one or more downstream dependencies are still warming up, saturated, or unavailable. When that happens, customer traffic may reach an API pod that cannot complete the request path.

The goal of this change is to make readiness represent real serving capability, not just process liveness.

## 2. Problem

The current readiness signal is too shallow for payment routing. It confirms that the process is running, but it does not consistently prove that critical dependencies are healthy. A pod can therefore enter service before database pools, Redis, Kafka producers, or gRPC clients are ready.

This creates three user-visible risks:

1. Newly rolled out pods may receive traffic before dependency connections are established.
2. Pods under dependency pressure may continue receiving traffic even when success probability is low.
3. On-call engineers get noisy symptoms instead of one clear readiness signal.

## 3. Current workflow

1. Kubernetes starts a payment API pod.
2. The application process boots and exposes health endpoints.
3. The service routes traffic once the pod is considered ready.
4. Runtime handlers discover dependency failures only after live requests arrive.
5. Failed requests must be retried or handled by upstream systems.

The weakness is that readiness is not aligned with the real payment path.

## 4. Proposed workflow

1. Kubernetes starts a payment API pod.
2. The application boots and checks critical dependencies.
3. The readiness endpoint verifies database connectivity, pool headroom, Redis availability, Kafka producer health, and required gRPC client readiness.
4. Kubernetes routes traffic only when these checks pass.
5. If a critical dependency becomes unhealthy, the pod is temporarily removed from traffic until it recovers.

The readiness endpoint becomes a contract: if the pod is ready, it can serve the payment path.

## 5. Architecture notes

The API pod owns request handling and exposes /ready. It should keep /live focused on process liveness so Kubernetes does not restart pods for temporary downstream dependency pressure.

Readiness should check both a lightweight database ping and pool starvation indicators. Redis readiness is required for paths that depend on idempotency, caching, or compliance state. Kafka producer readiness is required when the API pod must publish events as part of the request lifecycle. Critical downstream gRPC clients should expose connectivity and in-flight pressure signals.

## 6. Rollout plan

1. Add dependency-specific readiness checks behind safe defaults.
2. Enable checks for one low-risk API pod.
3. Watch readiness transitions, request error rate, latency, and pod churn.
4. Roll out to payment, mandate, auth, customer, gateway, and router pods.
5. Document which dependencies are critical for each API pod.

## 7. Success metrics

- Fewer 5xx errors during deployment windows.
- Lower request latency during dependency warm-up.
- Faster on-call diagnosis when dependencies are degraded.
- Readiness failures correlate with real inability to serve traffic.
- No increase in unnecessary pod restarts.

## 8. Explainer goal

The video should show the difference between alive and ready. Start with a pod receiving traffic too early, then show a dependency checklist gating service membership. End with the message: route traffic only to pods that can complete the payment path.`;
