/**
 * Agent log section — thin re-export of the design-system `AgentMonitor`
 * layout (`src/pages/AgentMonitor.tsx`). The pure `diffToEvents` /
 * `snapshotToKey` helpers are re-exported here because existing unit tests
 * import them from this path.
 */

export { default, diffToEvents, snapshotToKey } from '../../pages/AgentMonitor';
