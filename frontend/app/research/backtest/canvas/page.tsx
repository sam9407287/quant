import { redirect } from "next/navigation";

// There is one canvas now. The killzone blocks this page used to host are
// modules on the strategy canvas (Session / Killzone / Bracket), where they
// compose with the indicator rules instead of living in a parallel graph.
// The parameter form at /research/backtest is untouched — it is still the
// only path to USD P&L with slippage and commission.
export default function BacktestCanvasPage() {
  redirect("/research/strategies/canvas");
}
