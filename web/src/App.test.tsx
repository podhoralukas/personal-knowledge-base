import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";
import { fakeApi, item } from "@/test/fakeApi";
import { renderApp } from "@/test/render";

async function logIn(token: string) {
  const field = await screen.findByLabelText("Token");
  await userEvent.clear(field);
  await userEvent.type(field, token);
  await userEvent.click(screen.getByRole("button", { name: "Log in" }));
}

test("asks for the token, then shows the items", async () => {
  fakeApi({ items: [item({ id: "a", title: "Soup ideas" })], loggedIn: false });
  renderApp();

  await logIn("wrong");
  expect(await screen.findByRole("alert")).toHaveTextContent("Wrong token.");

  await logIn("secret");
  expect(await screen.findByRole("heading", { name: "Soup ideas", level: 3 })).toBeInTheDocument();
  expect(screen.queryByLabelText("Token")).not.toBeInTheDocument();
});

test("logging out asks for the token again", async () => {
  fakeApi({ items: [item({ id: "a", title: "Soup ideas" })] });
  renderApp();
  await screen.findByRole("heading", { name: "Soup ideas", level: 3 });

  await userEvent.click(screen.getByRole("button", { name: "Log out" }));
  expect(await screen.findByLabelText("Token")).toBeInTheDocument();
});
