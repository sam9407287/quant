import Link from "next/link";

import { ResearchWizard } from "@/components/research/wizard";

export default function ResearchPage() {
  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Research</h1>
          <p className="mt-2 max-w-3xl text-sm text-zinc-400">
            No-code ML workbench for the futures dataset. Pick data, engineer
            features, choose a model, and train end-to-end. Each run lands
            in the experiments table — see{" "}
            <Link
              href="/research/experiments"
              className="text-accent-blue hover:underline"
            >
              past experiments
            </Link>
            .
          </p>
        </div>
      </header>
      <ResearchWizard />
    </div>
  );
}
