import { CopyIcon } from "lucide-react";
import type { ReactNode } from "react";
import { toast } from "sonner";
import type { SessionRecord, SessionSummary } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Dot, SectionLabel } from "./bits";

/** Quoted only when the shell needs it, so the usual command stays readable. */
function shellQuoted(value: string): string {
  return /^[\w@%+=:,./-]+$/.test(value) ? value : `'${value.replaceAll("'", `'\\''`)}'`;
}

/** The way back to the conversation (D46): the apps reopen a Session by id, from the folder it ran in. */
export function resumeCommand({ agent, session_id, folder }: SessionRecord["meta"]): string {
  const id = shellQuoted(session_id);
  return `cd ${shellQuoted(folder)} && ${agent === "codex" ? `codex resume ${id}` : `claude --resume ${id}`}`;
}

/** A Session Summary with where its Session ran and how to get back to it. */
export function SessionView({ record }: { record: SessionRecord }) {
  const { meta, summary, after_the_fact: afterTheFact } = record;
  const facts = [summary.status, meta.agent, meta.model, meta.branch, afterTheFact && "written afterwards"].filter(Boolean);
  return (
    <>
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.85rem] text-muted-foreground">
        {facts.map((fact, i) => (
          <span key={String(fact)} className="contents">
            {i > 0 && <Dot />}
            <span>{fact}</span>
          </span>
        ))}
      </p>
      <section className="grid gap-2">
        <SectionLabel>Back to the conversation</SectionLabel>
        <Resume command={resumeCommand(meta)} />
        {meta.agent === "claude-code" && (
          <a
            href={`vscode://anthropic.claude-code/open?session=${encodeURIComponent(meta.session_id)}`}
            className="ml-1.5 w-fit text-[0.85rem] text-primary hover:underline"
          >
            Open in VS Code ↗
          </a>
        )}
        <dl className="ml-1.5 grid gap-1 text-[0.85rem]">
          {meta.repo_url && <Fact label="Repository" value={meta.repo_url} />}
          {meta.transcript_path && <Fact label="Transcript" value={meta.transcript_path} />}
        </dl>
      </section>
      <SessionSections summary={summary} />
    </>
  );
}

function Resume({ command }: { command: string }) {
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      toast("Command copied.");
    } catch {
      toast.error("Couldn't copy the command.");
    }
  };
  return (
    <div className="flex items-start justify-between gap-2 rounded-lg bg-muted px-3 py-2">
      <code className="font-mono text-[0.8rem] [overflow-wrap:anywhere]">{command}</code>
      <Button variant="ghost" size="icon" aria-label="Copy the command" onClick={copy}>
        <CopyIcon />
      </Button>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-wrap gap-x-2">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-mono text-[0.8rem] [overflow-wrap:anywhere]">{value}</dd>
    </div>
  );
}

/** The sections the agent wrote; an empty one is left out. */
export function SessionSections({ summary: s }: { summary: SessionSummary }) {
  return (
    <>
      {s.goal && <Prose label="Goal">{s.goal}</Prose>}
      {s.outcome && <Prose label="Outcome">{s.outcome}</Prose>}
      <Lines
        label="Decisions"
        lines={(s.decisions ?? []).map((d) => (
          <Detailed main={d.decision} details={[["Reason", d.reason], ["Rejected", d.rejected]]} />
        ))}
      />
      <Lines
        label="Problems"
        lines={(s.problems ?? []).map((p) => (
          <Detailed main={p.symptom} details={[["Cause", p.cause], ["Fix", p.fix]]} />
        ))}
      />
      <Lines label="Dropped" lines={s.dropped ?? []} />
      <Lines label="Todo" lines={s.todo ?? []} />
      <Lines label="Sources" lines={s.sources ?? []} />
      {(s.keywords?.length ?? 0) > 0 && (
        <section>
          <SectionLabel>Keywords</SectionLabel>
          <p className="ml-1.5 font-mono text-[0.8rem] [overflow-wrap:anywhere] text-muted-foreground">
            {s.keywords!.join(" · ")}
          </p>
        </section>
      )}
    </>
  );
}

function Prose({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section>
      <SectionLabel>{label}</SectionLabel>
      <p className="font-serif leading-relaxed [overflow-wrap:anywhere]">{children}</p>
    </section>
  );
}

function Lines({ label, lines }: { label: string; lines: ReactNode[] }) {
  if (lines.length === 0) return null;
  return (
    <section>
      <SectionLabel>{label}</SectionLabel>
      <ul className="grid list-disc gap-2 pl-5 font-serif leading-normal [overflow-wrap:anywhere] marker:text-primary">
        {lines.map((line, i) => (
          <li key={i}>{line}</li>
        ))}
      </ul>
    </section>
  );
}

function Detailed({ main, details }: { main: string; details: [string, string | undefined][] }) {
  return (
    <>
      {main}
      {details.map(
        ([label, text]) =>
          text && (
            <p key={label} className="text-[0.92rem] text-muted-foreground">
              <span className="font-sans text-[0.8rem] font-medium">{label}:</span> {text}
            </p>
          ),
      )}
    </>
  );
}
