import type { Metadata } from "next";
import { Workspace } from "@/components/app/workspace";

export const metadata: Metadata = {
  title: "Analyst · SandboxAnalyst",
};

export default function AppPage() {
  return <Workspace />;
}
