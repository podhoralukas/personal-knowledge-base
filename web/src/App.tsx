import { isUnauthorized } from "@/api/client";
import { useStats } from "@/api/queries";
import { LoginForm } from "@/components/LoginForm";
import { Shell } from "@/components/Shell";
import { Toaster } from "@/components/ui/sonner";

/** The login form until the API accepts the login cookie, then the app. */
export function App() {
  const session = useStats();
  if (session.isPending) return null;
  return (
    <>
      {isUnauthorized(session.error) ? <LoginForm /> : <Shell />}
      <Toaster position="bottom-center" />
    </>
  );
}
