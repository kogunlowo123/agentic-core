# ADR-0003: Enforce data classification before routing and failover

- Status: Accepted
- Date: 2026-10-14

## Context

Failover is the moment a router is most likely to send data somewhere it
should not go: the approved provider is down and the next one in the list
may sit in another jurisdiction or lack a BAA. Cost- and latency-based
ordering has the same risk.

## Decision

`ModelRouter.plan` first removes every provider whose
`ProviderProfile.max_classification` is below the request classification,
or that does not serve the requested task. Ordering, retries, circuit
breaking and failover operate only on the remaining set. If the set is
empty the router raises `ProviderUnavailableError` without calling any
provider.

`max_classification` is operator configuration reviewed through GitOps. It
should reflect contractual and regulatory approval (for example a signed BAA
for PHI or an approved data residency region), not technical capability.

## Consequences

- An outage of all approved providers causes a hard failure instead of a
  silent downgrade. That is intentional for regulated data; callers decide
  whether to queue, degrade or escalate.
- The invariant is checked by a property-based fault-injection test over
  random provider scripts and classifications.
