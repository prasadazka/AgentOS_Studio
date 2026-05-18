"use client";

import { useState } from "react";
import { ShieldCheck, X, Check, XCircle } from "lucide-react";

interface HITLDialogProps {
  request: {
    type: string;
    prompt: string;
    node_id: string;
    context?: Record<string, unknown>;
  };
  onRespond: (action: "approve" | "reject", comment?: string) => void;
  onClose: () => void;
}

export default function HITLDialog({ request, onRespond, onClose }: HITLDialogProps) {
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleAction(action: "approve" | "reject") {
    setSubmitting(true);
    onRespond(action, comment || undefined);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm">
      <div className="bg-white rounded-xl shadow-xl border border-[var(--border-light)] w-full max-w-md mx-4">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border-light)]">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-teal-50 flex items-center justify-center">
              <ShieldCheck className="w-4.5 h-4.5 text-teal-600" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-gray-900">Approval Required</h3>
              <span className="text-[10px] text-gray-500">Node: {request.node_id}</span>
            </div>
          </div>
          <button type="button" onClick={onClose} className="p-1 text-gray-400 hover:text-gray-600 rounded">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 space-y-3">
          <p className="text-sm text-gray-700">{request.prompt}</p>

          {request.context?.current_output ? (
            <div className="p-3 bg-gray-50 rounded-lg border border-[var(--border-light)]">
              <div className="text-[10px] font-medium text-gray-500 mb-1">Context</div>
              <div className="text-xs text-gray-700 whitespace-pre-wrap">
                {String(request.context.current_output)}
              </div>
            </div>
          ) : null}

          <div>
            <label className="text-[10px] font-medium text-gray-500 uppercase tracking-wide">Comment (optional)</label>
            <textarea
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              className="mt-1 w-full px-3 py-2 text-xs border border-[var(--border-light)] rounded-lg focus:outline-none focus:border-primary-500 h-16 resize-none"
              placeholder="Add a note..."
            />
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-[var(--border-light)] bg-gray-50 rounded-b-xl">
          <button
            type="button"
            onClick={() => handleAction("reject")}
            disabled={submitting}
            className="flex items-center gap-1.5 px-4 py-2 text-xs font-medium text-red-600 bg-white border border-red-200 rounded-lg hover:bg-red-50 transition-colors disabled:opacity-50"
          >
            <XCircle className="w-3.5 h-3.5" />
            Reject
          </button>
          <button
            type="button"
            onClick={() => handleAction("approve")}
            disabled={submitting}
            className="flex items-center gap-1.5 px-4 py-2 text-xs font-medium text-white bg-emerald-600 rounded-lg hover:bg-emerald-700 transition-colors disabled:opacity-50"
          >
            <Check className="w-3.5 h-3.5" />
            Approve
          </button>
        </div>
      </div>
    </div>
  );
}
