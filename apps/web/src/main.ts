import { mount } from "./app";

const root = document.getElementById("app");
if (root === null) {
  throw new Error("Repro: #app root element is missing from index.html");
}
mount(root);
