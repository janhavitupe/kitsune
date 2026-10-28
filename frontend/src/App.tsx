import { useEffect, useState } from "react";
import RepoPage from "./pages/RepoPage";
import RepoPicker from "./pages/RepoPicker";

/** The open repo lives in the URL (?repo=3) so a reload or a shared link lands in the same place. */
function readRepoId(): number | null {
  const id = Number(new URLSearchParams(window.location.search).get("repo"));
  return Number.isInteger(id) && id > 0 ? id : null;
}

export default function App() {
  const [repoId, setRepoId] = useState<number | null>(readRepoId);

  useEffect(() => {
    const onPop = () => setRepoId(readRepoId());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const open = (id: number | null) => {
    const url = id === null ? window.location.pathname : `?repo=${id}`;
    window.history.pushState(null, "", url);
    setRepoId(id);
  };

  return repoId === null ? (
    <RepoPicker onOpen={open} />
  ) : (
    <RepoPage repoId={repoId} onBack={() => open(null)} />
  );
}
