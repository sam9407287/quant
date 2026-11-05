import type { Metadata } from "next";
import Link from "next/link";

import { PairsHeader } from "@/components/pairs/subnav";

export const metadata: Metadata = { title: "Pairs lab guide" };

const H2 = "text-lg font-semibold text-zinc-100 scroll-mt-24";
const H3 = "mt-5 text-sm font-semibold text-zinc-200";
const P = "text-sm leading-relaxed text-zinc-400";
const CARD = "rounded-lg border border-border bg-bg-panel p-6 space-y-3";
const CODE = "rounded bg-bg-hover px-1.5 py-0.5 font-mono text-[12px] text-zinc-200";
const TH = "px-3 py-2 text-left text-[10px] font-mono uppercase tracking-wider text-zinc-500";
const TD = "px-3 py-2 align-top text-xs text-zinc-400";
const TDK = "px-3 py-2 align-top font-mono text-xs text-zinc-200 whitespace-nowrap";

const TOC = [
  ["what", "What this is"],
  ["workflow", "The research workflow"],
  ["concepts", "Core concepts"],
  ["qualification", "When a pair qualifies"],
  ["signals", "Signal rules"],
  ["sizing", "Hedge sizing"],
  ["backtest", "Reading a backtest"],
  ["pages", "Page by page"],
  ["data", "Data caveats"],
  ["job", "The daily job and Discord"],
  ["glossary", "Glossary"],
  ["limits", "Known limits and next steps"],
];

export default function GuidePage() {
  return (
    <div className="space-y-6">
      <PairsHeader title="Pairs lab guide">
        What the statistical arbitrage lab does, how to use each page, and what every number means. Read top to
        bottom once; afterwards the glossary at the end is the part you will come back to.
      </PairsHeader>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[220px_1fr]">
        <aside className="hidden lg:block">
          <nav className="sticky top-6 space-y-1 rounded-lg border border-border bg-bg-panel p-3 text-xs">
            {TOC.map(([id, label], i) => (
              <a key={id} href={`#${id}`} className="block rounded px-2 py-1 text-zinc-400 hover:bg-bg-hover hover:text-zinc-100">
                <span className="mr-2 font-mono text-zinc-600">{String(i + 1).padStart(2, "0")}</span>
                {label}
              </a>
            ))}
          </nav>
        </aside>

        <div className="space-y-6">
          <section id="what" className={CARD}>
            <h2 className={H2}>1 · What this is</h2>
            <p className={P}>
              A pairs trade bets that two prices that have moved together will keep moving together. You go long the
              one that has fallen behind and short the one that has run ahead, in a ratio chosen so that the combined
              position is insensitive to the market as a whole. If the historical relationship holds, the gap closes
              and the trade earns the gap; if the relationship has broken, it does not.
            </p>
            <p className={P}>
              The lab turns that idea into a repeatable, measurable process. It keeps a daily price history for a
              universe of futures, ETFs and stocks; tests every candidate pair for <em>cointegration</em> (the
              statistical form of &ldquo;moves together&rdquo;); turns the spread between the two legs into a
              z-score; backtests entry and exit rules walk-forward with explicit costs; and runs the same decision
              logic every evening against the watchlist, pushing changes to Discord.
            </p>
            <p className={P}>
              It is a <strong className="text-zinc-200">research arena</strong>, not an order router. Nothing here
              trades. Every alert says what the model would do and why, and the decision stays yours.
            </p>
          </section>

          <section id="workflow" className={CARD}>
            <h2 className={H2}>2 · The research workflow</h2>
            <ol className="space-y-3 text-sm text-zinc-400">
              <li>
                <strong className="text-zinc-200">Load data.</strong> On the dashboard press <em>Refresh data</em>.
                New tickers download ten years of daily bars; known ones refresh a two-week overlap so revised
                settlements are picked up.
              </li>
              <li>
                <strong className="text-zinc-200">Scan.</strong> Run a scan over the watchlist (the ten pairs from
                the brief) or the whole universe. Every ordered pair gets the full evidence table; the rolling
                stability test runs only for pairs that pass the cheap filters. The result is a ranked table with a
                qualified / not-qualified verdict and the reasons.
              </li>
              <li>
                <strong className="text-zinc-200">Analyze.</strong> Open a pair. Look at the spread, at how β and
                the p-value drifted, and above all at the <em>conditional forward returns</em>: when z was beyond
                ±2, did the spread actually come back over the next 5–20 days? If that table is flat, no rule will
                rescue the pair.
              </li>
              <li>
                <strong className="text-zinc-200">Backtest.</strong> Run the walk-forward engine over the pairs
                that survive, with costs on and the sensitivity grid enabled. Judge the result by the deflated
                Sharpe and the plateau in the grid, never by the best cell.
              </li>
              <li>
                <strong className="text-zinc-200">Watch.</strong> Put the survivors on the watchlist. The daily job
                scans them after the US close, keeps a position state per pair and pushes every state change to
                Discord. Run it in dry-run mode for two weeks first and compare its decisions with the backtest.
              </li>
              <li>
                <strong className="text-zinc-200">Paper trade.</strong> Record what you would have done against what
                the job said for three to six months. The gap between the paper record and the backtest is the
                number that decides whether real capital is sensible.
              </li>
            </ol>
          </section>

          <section id="concepts" className={CARD}>
            <h2 className={H2}>3 · Core concepts</h2>

            <h3 className={H3}>Cointegration is not correlation</h3>
            <p className={P}>
              Correlation says the daily <em>returns</em> of two assets tend to have the same sign. Cointegration
              says a fixed combination of their <em>price levels</em> is stationary: it wanders but keeps coming
              back to a mean. Two assets can be highly correlated and still drift apart forever (think of two tech
              stocks with different growth), and two assets can have weak daily correlation yet be tied by an
              arbitrage relationship (the same oil delivered in two places). Pairs trading needs the second
              property. The lab reports both so the difference is visible.
            </p>

            <h3 className={H3}>The regression and the spread</h3>
            <p className={P}>
              All tests use log prices. The hedge regression is <span className={CODE}>log Y = α + β·log X + ε</span>.
              β is the <em>hedge ratio</em>: a 1 % move in X maps to a β % move in Y. The residual ε is the{" "}
              <em>spread</em>, and the whole strategy is a statement about ε: it should be stationary with a
              half-life short enough to trade.
            </p>
            <p className={P}>
              Three estimators of β are shown side by side. <strong className="text-zinc-300">OLS</strong> is the
              textbook one but treats X as noise-free, which is why β(Y on X) is not 1/β(X on Y).{" "}
              <strong className="text-zinc-300">TLS</strong> (orthogonal regression) is symmetric in the legs.{" "}
              <strong className="text-zinc-300">Johansen</strong> comes from a system estimate. If the three
              disagree a lot, the relationship is poorly identified and position sizing will be fragile.
            </p>

            <h3 className={H3}>The evidence stack</h3>
            <p className={P}>
              One p-value is a weak reason to risk money, so each pair gets several independent tests:
            </p>
            <table className="min-w-full">
              <thead className="border-b border-border">
                <tr>
                  <th className={TH}>Test</th>
                  <th className={TH}>What it checks</th>
                  <th className={TH}>Read it as</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                <tr>
                  <td className={TDK}>Engle-Granger (both ways)</td>
                  <td className={TD}>Whether the OLS residual has a unit root. The default gate.</td>
                  <td className={TD}>p &lt; 0.05 in both directions is the comfortable case; agreement matters more than the exact value.</td>
                </tr>
                <tr>
                  <td className={TDK}>ADF on the spread</td>
                  <td className={TD}>The same question asked of the spread directly.</td>
                  <td className={TD}>Should agree with Engle-Granger; a split is a warning.</td>
                </tr>
                <tr>
                  <td className={TDK}>Johansen trace</td>
                  <td className={TD}>System test for at least one cointegrating vector.</td>
                  <td className={TD}>Statistic above the 95 % critical value = pass. Used as cross-validation, optional as a gate.</td>
                </tr>
                <tr>
                  <td className={TDK}>Hurst exponent</td>
                  <td className={TD}>Long-memory scaling of the spread.</td>
                  <td className={TD}>Below 0.5 mean reverting, 0.5 random walk, above trending. A rough estimate; one voice, not a verdict.</td>
                </tr>
                <tr>
                  <td className={TDK}>BH q-value</td>
                  <td className={TD}>Engle-Granger p-value corrected for the number of pairs tested in the scan (Benjamini–Hochberg).</td>
                  <td className={TD}>Scanning 1 800 ordered pairs at p &lt; 0.05 yields ~90 false positives by chance. The q-value is the honest number.</td>
                </tr>
              </tbody>
            </table>

            <h3 className={H3}>Half-life</h3>
            <p className={P}>
              Fitting <span className={CODE}>Δs(t) = λ·s(t−1) + c</span> gives the speed of mean reversion; the
              half-life is <span className={CODE}>−ln 2 / λ</span>, the number of days for half of a deviation to
              decay. λ ≥ 0 means no reversion at all and disqualifies the pair outright. The point estimate is
              noisy on two years of data, so the lab also shows a block-bootstrap 90 % interval: &ldquo;HL = 8
              (5–16)&rdquo; is a different statement from &ldquo;HL = 8&rdquo;.
            </p>

            <h3 className={H3}>z-score and its window</h3>
            <p className={P}>
              <span className={CODE}>z = (spread − mean) / std</span> over a trailing window. The brief proposed a
              window of 2 × half-life. On synthetic spreads with a known half-life that window understates the
              stationary variance (it spans only two half-lives), inflates z, and fires the 3.5σ stop on most
              trades: the same cointegrated pair that scores a Sharpe of 1.4–1.7 with a 60-day window scores ≈ 0
              with 2 × HL. The lab therefore defaults to{" "}
              <span className={CODE}>window = clip(4 × HL, 20, 120)</span> and exposes the multiple as a parameter
              so the choice can be tested rather than assumed.
            </p>
          </section>

          <section id="qualification" className={CARD}>
            <h2 className={H2}>4 · When a pair qualifies</h2>
            <p className={P}>All conditions must hold at the scan date; each is configurable.</p>
            <table className="min-w-full">
              <thead className="border-b border-border">
                <tr>
                  <th className={TH}>Condition</th>
                  <th className={TH}>Default</th>
                  <th className={TH}>Why</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                <tr>
                  <td className={TDK}>Engle-Granger p</td>
                  <td className={TDK}>&lt; 0.05</td>
                  <td className={TD}>The relationship exists at conventional confidence.</td>
                </tr>
                <tr>
                  <td className={TDK}>Half-life</td>
                  <td className={TDK}>3 – 40 days</td>
                  <td className={TD}>Shorter is noise and execution cost; longer ties capital up for months and is hard to distinguish from a trend.</td>
                </tr>
                <tr>
                  <td className={TDK}>Stability</td>
                  <td className={TDK}>≥ 80 % of last 60 days with p &lt; 0.05</td>
                  <td className={TD}>A pair that only just passed today is often a pair that fails next week. This is the main defence against false positives.</td>
                </tr>
                <tr>
                  <td className={TDK}>β sign and drift</td>
                  <td className={TDK}>β &gt; 0, CV of rolling β &lt; 0.5</td>
                  <td className={TD}>A negative β is a different trade; a β that swings is a hedge that cannot be sized.</td>
                </tr>
              </tbody>
            </table>
            <p className={P}>
              The stability test is expensive (one regression and unit-root test per day), so the scan only runs it
              for pairs that already pass the point-in-time conditions. Pairs that fail show the cheapest failing
              reason first in the table; hover for the rest.
            </p>
          </section>

          <section id="signals" className={CARD}>
            <h2 className={H2}>5 · Signal rules</h2>
            <p className={P}>
              One state machine drives both the backtest and the daily job, so the backtest is a statement about
              the live system rather than a cousin of it. Decisions happen at the close; fills happen the next day.
            </p>
            <table className="min-w-full">
              <thead className="border-b border-border">
                <tr>
                  <th className={TH}>Rule</th>
                  <th className={TH}>Default</th>
                  <th className={TH}>Note</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                <tr>
                  <td className={TDK}>Entry</td>
                  <td className={TDK}>z ≥ +2 short spread · z ≤ −2 long spread</td>
                  <td className={TD}>Short spread = sell Y, buy β·X in notional. Long spread is the mirror.</td>
                </tr>
                <tr>
                  <td className={TDK}>Exit</td>
                  <td className={TDK}>|z| ≤ 0.5, or z crosses zero</td>
                  <td className={TD}>Both variants are in the sensitivity grid; cross-zero holds longer and earns more per trade when the pair is honest.</td>
                </tr>
                <tr>
                  <td className={TDK}>Stop</td>
                  <td className={TDK}>|z| ≥ 3.5 against the position</td>
                  <td className={TD}>Followed by a cooldown. Only adverse moves stop; a favourable overshoot is simply a bigger win.</td>
                </tr>
                <tr>
                  <td className={TDK}>Time stop</td>
                  <td className={TDK}>held &gt; 3 × half-life</td>
                  <td className={TD}>If it has not reverted in three half-lives, the half-life was wrong.</td>
                </tr>
                <tr>
                  <td className={TDK}>Breakdown</td>
                  <td className={TDK}>EG p &gt; 0.10 for 5 consecutive days</td>
                  <td className={TD}>The relationship itself has failed while you are in it: exit, cooldown, and the pair stops qualifying for new entries.</td>
                </tr>
                <tr>
                  <td className={TDK}>Parameter freeze</td>
                  <td className={TDK}>on</td>
                  <td className={TD}>β, mean and std are fixed at entry so the exit is judged against what was known then. Switch off to compare with daily refreshed parameters.</td>
                </tr>
              </tbody>
            </table>
            <p className={P}>Priority when several fire on the same day: stop → breakdown → time stop → exit. An exit never re-enters the same day.</p>
          </section>

          <section id="sizing" className={CARD}>
            <h2 className={H2}>6 · Hedge sizing</h2>
            <p className={P}>
              Because β is a log-price elasticity, the position that tracks the spread has{" "}
              <span className={CODE}>notional(X) = β × notional(Y)</span>, where notional = quantity × price ×
              contract multiplier. (The brief wrote it the other way round; with a log regression this is the
              correct direction.) Given a gross notional budget per pair, the Y leg gets{" "}
              <span className={CODE}>budget / (1 + β)</span> and the X leg the rest.
            </p>
            <p className={P}>
              <strong className="text-zinc-300">Fractional</strong> sizing is the research truth: legs can be any
              real quantity, so the ratio is exactly β. <strong className="text-zinc-300">Integer</strong> sizing
              rounds to whole contracts, micro contracts first (MNQ, MES, MGC, MCL…), reports how far the realised
              ratio drifted from β, and marks positions that round to zero as infeasible. Running both gives the{" "}
              <em>tradeability tax</em>: the return you lose purely to lot sizes. Entry alerts also carry a
              two-sigma adverse-move estimate in dollars on the Y notional.
            </p>
          </section>

          <section id="backtest" className={CARD}>
            <h2 className={H2}>7 · Reading a backtest</h2>
            <h3 className={H3}>What makes it walk-forward</h3>
            <p className={P}>
              For every trading day t, α, β, half-life, the z window and the p-value are computed from the
              formation window that ends at t−1. The signal is evaluated at t&rsquo;s close and filled at t+1&rsquo;s
              open (or close). A test in the code base randomises every price after a date T and asserts that every
              trade and every equity point up to T is identical, so nothing can leak backwards.
            </p>
            <h3 className={H3}>Costs</h3>
            <p className={P}>
              Commission per contract per side, slippage in ticks per leg per fill (converted with each
              contract&rsquo;s tick value), and a roll cost per leg: charged on the roll calendar&rsquo;s dates for
              equity index futures, otherwise as a daily expectation from the instrument&rsquo;s contract months per
              year. ETFs and stocks have no roll cost.
            </p>
            <h3 className={H3}>Portfolio</h3>
            <p className={P}>
              Capital × gross leverage is split equally across the pairs in the run (or by inverse spread
              volatility). <em>Max concurrent</em> caps how many pairs can be open at once; a signal that arrives
              when the slots are full is skipped, not queued. The P&amp;L correlation heatmap shows whether your
              pairs are one bet in disguise — NQ/ES, ES/YM and NQ/YM usually are.
            </p>
            <h3 className={H3}>The honesty metrics</h3>
            <ul className="list-disc space-y-1 pl-5 text-sm text-zinc-400">
              <li>
                <strong className="text-zinc-300">Sharpe with a bootstrap interval.</strong> Blocks of 20 days are
                resampled 500 times. If the interval straddles zero the point estimate is not telling you much.
              </li>
              <li>
                <strong className="text-zinc-300">Deflated Sharpe probability.</strong> With the sensitivity grid
                on, the engine ran N parameter combinations; the best of N zero-skill strategies would also look
                good. The deflated Sharpe is the probability that the true Sharpe beats that best-of-N null, using
                the observed dispersion of the grid, skew and kurtosis. Below ≈ 0.9 the result could be selection.
              </li>
              <li>
                <strong className="text-zinc-300">Benchmark.</strong> Equal-weight buy-and-hold of the Y legs over
                the same span, with its own drawdown, so the strategy is compared with the simplest alternative.
              </li>
              <li>
                <strong className="text-zinc-300">Exit mix.</strong> A strategy that exits mostly on stops is a
                strategy whose z window or stop level is wrong, whatever the total return says.
              </li>
              <li>
                <strong className="text-zinc-300">Sensitivity plateau.</strong> Choose parameters from a region of
                the grid that is uniformly acceptable. A lone bright cell is noise.
              </li>
            </ul>
          </section>

          <section id="pages" className={CARD}>
            <h2 className={H2}>8 · Page by page</h2>
            <h3 className={H3}>
              <Link href="/research/pairs" className="text-accent-blue hover:underline">Dashboard</Link>
            </h3>
            <p className={P}>
              Six blocks in reading order: data coverage and actions; the latest scan as a sortable table (click a
              header); the watchlist the daily job uses; the live state per pair with the frozen entry parameters;
              the signal feed (pushed or not); and the job history. &ldquo;no_data&rdquo; in the job list is the
              normal outcome on a US holiday.
            </p>
            <h3 className={H3}>
              <Link href="/research/pairs/analyze" className="text-accent-blue hover:underline">Analyze</Link>
            </h3>
            <p className={P}>
              Pick Y and X (or arrive from a dashboard link or a Discord alert). Tiles summarise the current
              state; the evidence table lists every test; the two charts show the spread/z and β/p through time;
              the forward-return table is the diagnostic that matters most. Cross-group pairs show a settlement
              note — switch the price source to the 15:00 ET snapshot to read both legs at the same instant.
            </p>
            <h3 className={H3}>
              <Link href="/research/pairs/backtest" className="text-accent-blue hover:underline">Backtest</Link>
            </h3>
            <p className={P}>
              Four blocks of configuration (pairs, estimation, rules and costs, capital and sizing), then results:
              metric tiles with hover explanations, equity and drawdown, per-pair attribution, correlation,
              sensitivity heatmaps and the trade list. Earlier runs reopen from the table at the bottom and reload
              their configuration into the form.
            </p>
          </section>

          <section id="data" className={CARD}>
            <h2 className={H2}>9 · Data caveats</h2>
            <ul className="list-disc space-y-2 pl-5 text-sm text-zinc-400">
              <li>
                <strong className="text-zinc-300">Front-month futures series roll.</strong> The vendor&rsquo;s{" "}
                <span className={CODE}>=F</span> tickers are unadjusted front-month series; on roll day the price
                jumps by the calendar spread and the pairs spread sees a shock that is not a trading opportunity.
                Equity index pairs read the project&rsquo;s roll calendar and the charts mark those dates; other
                futures flag large single-day moves as &ldquo;gaps&rdquo; in the scan table. A continuous,
                back-adjusted series from a paid vendor is the proper fix and remains an open purchase decision.
              </li>
              <li>
                <strong className="text-zinc-300">Settlement times differ.</strong> Gold settles at 13:30 ET, oil
                at 14:30, Treasuries at 15:00, equity indices at 16:00. A settlement-based spread between two
                groups mixes two moments. The 1m store lets both legs be read at one wall-clock time instead; the
                option is on the Analyze page and in the scan configuration.
              </li>
              <li>
                <strong className="text-zinc-300">Adjusted closes for ETFs and stocks.</strong> Dividends would
                otherwise appear as spread shocks on every ex-date. Futures use the plain close.
              </li>
              <li>
                <strong className="text-zinc-300">Revisions.</strong> Vendors revise settlements for a day or two;
                the refresh overwrites, and the daily job always re-reads a two-week overlap.
              </li>
              <li>
                <strong className="text-zinc-300">Holidays.</strong> Legs are inner-joined on trading dates with at
                most one day of forward fill, so a single-exchange holiday is bridged and a longer hole is dropped
                rather than invented.
              </li>
            </ul>
          </section>

          <section id="job" className={CARD}>
            <h2 className={H2}>10 · The daily job and Discord</h2>
            <p className={P}>
              The job runs inside the fetcher process at 23:00 UTC on weekdays (two to three hours after the US
              close, with no change needed across daylight-saving transitions). Steps: refresh daily bars → confirm
              a bar exists for the expected trading date (otherwise record <em>no_data</em> and stop) → scan the
              watchlist → step each pair&rsquo;s state through the shared state machine → write state and events →
              push un-notified events to the webhook.
            </p>
            <p className={P}>
              It is safe to re-run on the same day: a pair already advanced to today&rsquo;s date is not stepped
              again, the signal log refuses duplicate (date, pair, event) rows, and only events without a push
              timestamp are posted. Admins can trigger a dry run from the dashboard.
            </p>
            <table className="min-w-full">
              <thead className="border-b border-border">
                <tr>
                  <th className={TH}>Variable</th>
                  <th className={TH}>Default</th>
                  <th className={TH}>Meaning</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                <tr><td className={TDK}>PAIRS_WEBHOOK_URL</td><td className={TDK}>—</td><td className={TD}>Discord webhook for alerts (keep it separate from the ops channel). Empty = nothing is posted.</td></tr>
                <tr><td className={TDK}>PAIRS_DRY_RUN</td><td className={TDK}>false</td><td className={TD}>Scan and persist, post nothing. Use it for the first two weeks.</td></tr>
                <tr><td className={TDK}>PAIRS_CRON</td><td className={TDK}>0 23 * * 1-5</td><td className={TD}>Schedule in UTC.</td></tr>
                <tr><td className={TDK}>PAIRS_CAPITAL</td><td className={TDK}>1 000 000</td><td className={TD}>Notional the entry alert sizes against (integer contracts, micro first).</td></tr>
                <tr><td className={TDK}>PAIRS_DAILY_DIGEST</td><td className={TDK}>true</td><td className={TD}>One compact message per day listing every watchlist pair&rsquo;s z, p and half-life.</td></tr>
                <tr><td className={TDK}>PAIRS_NOTIFY_NO_DATA</td><td className={TDK}>false</td><td className={TD}>Also post when no new bar arrived (holidays would otherwise be silent).</td></tr>
                <tr><td className={TDK}>PAIRS_HISTORY_YEARS</td><td className={TDK}>10</td><td className={TD}>History requested for tickers seen for the first time.</td></tr>
              </tbody>
            </table>
            <p className={P}>
              Each alert links back to the pair&rsquo;s Analyze page. An entry message shows z, β, half-life,
              p-value, stability, the suggested integer legs with their rounding error and the two-sigma adverse
              estimate; an exit message shows the reason and the days held. Every message ends with &ldquo;research
              only, not an order&rdquo;.
            </p>
          </section>

          <section id="glossary" className={CARD}>
            <h2 className={H2}>11 · Glossary</h2>
            <dl className="grid grid-cols-1 gap-x-8 gap-y-3 text-sm md:grid-cols-2">
              {[
                ["Spread", "log Y − α − β·log X. The thing that is supposed to mean-revert."],
                ["z", "Spread minus its trailing mean, divided by its trailing standard deviation."],
                ["β (hedge ratio)", "Slope of log Y on log X; sets notional(X) = β·notional(Y)."],
                ["Half-life (HL)", "Days for half of a spread deviation to decay, from the OU regression."],
                ["Formation window", "Trailing days used to estimate α, β and HL; 504 ≈ two years."],
                ["Stability", "Share of the last 60 days on which the pair tested cointegrated."],
                ["BH q-value", "False-discovery-rate adjusted p-value across all pairs in a scan."],
                ["Hit rate", "In the forward table: share of cases where the spread moved back toward its mean."],
                ["Long / short spread", "Long spread = buy Y, sell X. Short spread = sell Y, buy X."],
                ["Sharpe", "Annualised mean daily return over its standard deviation (zero risk-free rate)."],
                ["Sortino", "Like Sharpe but only downside deviation in the denominator."],
                ["Calmar", "Annual return divided by the absolute maximum drawdown."],
                ["CVaR 95", "Average of the worst 5 % of daily returns."],
                ["Deflated Sharpe p", "Probability the true Sharpe exceeds the best-of-N-trials null."],
                ["Tradeability tax", "Fractional-sizing return minus integer-contract return."],
                ["Breakdown", "EG p above threshold for consecutive days while in a position."],
                ["Dry run", "The job computes and records everything but posts nothing."],
                ["Snapshot source", "Prices read from the 1m store at one New York time for every leg."],
              ].map(([k, v]) => (
                <div key={k} className="border-b border-border/60 pb-2">
                  <dt className="font-mono text-xs text-zinc-200">{k}</dt>
                  <dd className="mt-0.5 text-xs text-zinc-500">{v}</dd>
                </div>
              ))}
            </dl>
          </section>

          <section id="limits" className={CARD}>
            <h2 className={H2}>12 · Known limits and next steps</h2>
            <ul className="list-disc space-y-2 pl-5 text-sm text-zinc-400">
              <li>Classic pairs-trading returns have declined since the 2000s in the academic record; expect thin edges and let the deflated Sharpe keep you honest.</li>
              <li>Relationships break for structural reasons (negative oil in 2020, a changed index methodology). The breakdown rule is a detector, not a prophecy; calibrate its threshold on the pairs you actually trade.</li>
              <li>Front-month roll gaps pollute every futures spread until a continuous series is sourced.</li>
              <li>The engine is two-legged. Johansen already produces the cointegrating vector for three or four legs (a Treasury-curve basket, NQ/ES/YM together); a basket engine is the natural next module.</li>
              <li>Position sizing is unconstrained by any account rule on purpose. If you later trade this inside a funded account, add that layer on top rather than inside the research code.</li>
              <li>Intraday signals are out of scope here even though the 1m store would support them; the daily cadence is deliberate for a swing horizon.</li>
            </ul>
            <p className={P}>
              Design record: <span className={CODE}>docs/ADR-010-pairs-lab.md</span> in the repository.
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}
