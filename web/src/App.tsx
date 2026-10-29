import { isUnauthorized } from "@/api/client";
import { useStats } from "@/api/queries";
import { LoginForm } from "@/components/LoginForm";
import { Shell } from "@/components/Shell";
import { TaxonomyPage } from "@/components/TaxonomyPage";
import { Toaster } from "@/components/ui/sonner";
import { usePage } from "@/lib/route";

/** The login form until the API accepts the login cookie, then the page the URL names. */
export function App() {
  const session = useStats();
  const page = usePage();
  if (session.isPending) return null;
  return (
    <>
      {isUnauthorized(session.error) ? <LoginForm /> : page === "taxonomy" ? <TaxonomyPage /> : <Shell />}
      <Toaster position="bottom-center" />
    </>
  );
}
