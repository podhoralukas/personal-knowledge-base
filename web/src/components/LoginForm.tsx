import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, isUnauthorized, unwrap } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/** Exchanges the API token for the login cookie, then reloads every query. */
export function LoginForm() {
  const queryClient = useQueryClient();
  const login = useMutation({
    mutationFn: async (token: string) => unwrap(await api.POST("/auth/login", { body: { token } })),
    onSuccess: () => queryClient.invalidateQueries(),
  });

  return (
    <main className="grid min-h-svh place-items-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Knowledge Base</CardTitle>
          <CardDescription>Log in with the API token from .env.</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="grid gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              login.mutate(String(new FormData(event.currentTarget).get("token")));
            }}
          >
            <Label htmlFor="token">Token</Label>
            <Input id="token" name="token" type="password" autoComplete="current-password" required autoFocus />
            {login.error && (
              <p role="alert" className="text-sm text-destructive">
                {isUnauthorized(login.error) ? "Wrong token." : login.error.message}
              </p>
            )}
            <Button type="submit" disabled={login.isPending}>
              Log in
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
