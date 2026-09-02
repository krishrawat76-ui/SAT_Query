"use client";

export type CloudPhase = "idle" | "covering" | "clearing";

interface CloudTransitionProps {
    phase: CloudPhase;
}

const EASE = "ease-[cubic-bezier(0.25,0.1,0.25,1)]";

// A brief GTA/Clash-style "puff" that only masks the very start of a camera
// switch — the flight itself plays out fully visible and unblurred, so
// satellite tiles stay sharp for the whole zoom-out/pan/zoom-in sequence.
export default function CloudTransition({ phase }: CloudTransitionProps) {
    if (phase === "idle") return null;

    const opacityClass =
        phase === "clearing" ? "duration-[900ms] opacity-0" : "duration-300 opacity-100";
    const scaleClass = phase === "clearing" ? "scale-125" : "scale-100";

    return (
        <div
            className={`pointer-events-none fixed inset-0 z-20 overflow-hidden transition-opacity ${EASE} ${opacityClass}`}
            aria-hidden="true"
        >
            <div className="absolute inset-0 bg-gradient-to-br from-slate-700/60 via-slate-800/40 to-transparent backdrop-blur-2xl" />

            <div className={`absolute -inset-1/3 transition-transform duration-[900ms] ${EASE} ${scaleClass}`}>
                <div className="absolute inset-0 animate-[cloud-drift_7s_ease-in-out_infinite] bg-[radial-gradient(circle_at_30%_35%,rgba(100,116,139,0.6),transparent_58%),radial-gradient(circle_at_68%_60%,rgba(71,85,105,0.5),transparent_52%)]" />
            </div>
            <div className={`absolute -inset-1/4 transition-transform duration-[900ms] ${EASE} ${scaleClass}`}>
                <div className="absolute inset-0 animate-[cloud-drift-reverse_10s_ease-in-out_infinite] bg-[radial-gradient(circle_at_55%_25%,rgba(148,163,184,0.35),transparent_60%),radial-gradient(circle_at_20%_75%,rgba(51,65,85,0.45),transparent_55%)]" />
            </div>
        </div>
    );
}
