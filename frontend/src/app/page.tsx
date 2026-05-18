"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Bot, Wrench, Plus, ArrowRight, Layers, FolderOpen } from "lucide-react";
import Header from "@/components/layout/Header";
import { api } from "@/lib/api";
import type { Stats, Agent } from "@/types";

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const [statsData, agentsData] = await Promise.all([
          api<Stats>("/api/stats"),
          api<{ agents: Agent[] }>("/api/agents"),
        ]);
        setStats(statsData);
        setAgents(agentsData.agents.slice(0, 6));
      } catch (e) {
        console.error("Failed to load dashboard:", e);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  return (
    <div className="flex flex-col h-full">
      <Header title="Dashboard" />

      <div className="flex-1 p-6 space-y-6">
        {/* Stats Row */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard
            icon={<FolderOpen className="w-5 h-5 text-blue-600" />}
            label="Projects"
            value={stats?.total_projects ?? "-"}
            bg="bg-blue-50"
          />
          <StatCard
            icon={<Bot className="w-5 h-5 text-primary-600" />}
            label="Total Agents"
            value={stats?.total_agents ?? "-"}
            bg="bg-primary-50"
          />
          <StatCard
            icon={<Wrench className="w-5 h-5 text-[var(--success)]" />}
            label="Total Tools"
            value={stats?.total_tools ?? "-"}
            bg="bg-green-50"
          />
          <StatCard
            icon={<Layers className="w-5 h-5 text-[var(--warning)]" />}
            label="Categories"
            value={stats?.total_categories ?? "-"}
            bg="bg-yellow-50"
          />
        </div>

        {/* Quick Actions */}
        <div className="flex gap-3">
          <Link
            href="/projects/new"
            className="flex items-center gap-2 px-4 py-2.5 bg-primary-600 text-white text-sm font-medium rounded-lg hover:bg-primary-700 transition-colors"
          >
            <Plus className="w-4 h-4" />
            New Project
          </Link>
          <Link
            href="/agents/new"
            className="flex items-center gap-2 px-4 py-2.5 bg-white text-gray-700 text-sm font-medium rounded-lg border border-[var(--border)] hover:bg-gray-50 transition-colors"
          >
            <Bot className="w-4 h-4" />
            Create Agent
          </Link>
          <Link
            href="/tools"
            className="flex items-center gap-2 px-4 py-2.5 bg-white text-gray-700 text-sm font-medium rounded-lg border border-[var(--border)] hover:bg-gray-50 transition-colors"
          >
            <Wrench className="w-4 h-4" />
            Browse Tools
          </Link>
        </div>

        {/* Agents Grid */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-gray-900">Agents</h2>
            <Link
              href="/agents"
              className="text-sm text-primary-600 hover:text-primary-700 flex items-center gap-1"
            >
              View all <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </div>

          {loading ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {[1, 2, 3].map((i) => (
                <div
                  key={i}
                  className="h-32 bg-white rounded-lg border border-[var(--border-light)] animate-pulse"
                />
              ))}
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {agents.map((agent) => (
                <Link
                  key={agent.name}
                  href={`/agents/${agent.name}`}
                  className="bg-white rounded-lg border border-[var(--border-light)] p-4 hover:shadow-card transition-shadow"
                >
                  <div className="flex items-start justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <div className="w-8 h-8 rounded-lg bg-primary-50 flex items-center justify-center">
                        <Bot className="w-4 h-4 text-primary-600" />
                      </div>
                      <span className="font-medium text-sm text-gray-900">
                        {agent.name}
                      </span>
                    </div>
                    {agent.is_default && (
                      <span className="text-[10px] font-medium px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded">
                        DEFAULT
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 text-xs text-gray-500">
                    <span className="px-1.5 py-0.5 bg-gray-50 rounded">
                      {agent.model}
                    </span>
                    <span>{agent.tools.length} tools</span>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  bg,
}: {
  icon: React.ReactNode;
  label: string;
  value: string | number;
  bg: string;
}) {
  return (
    <div className="bg-white rounded-lg border border-[var(--border-light)] p-4 flex items-center gap-4">
      <div className={`w-10 h-10 rounded-lg ${bg} flex items-center justify-center`}>
        {icon}
      </div>
      <div>
        <p className="text-2xl font-semibold text-gray-900">{value}</p>
        <p className="text-xs text-gray-500">{label}</p>
      </div>
    </div>
  );
}