const menu = document.querySelector(".menu-toggle"),
  nav = document.querySelector("#product-nav");
function closeMenu() {
  nav.classList.remove("is-open");
  menu.setAttribute("aria-expanded", "false");
  menu.textContent = "Menu";
}
menu.addEventListener("click", () => {
  const open = menu.getAttribute("aria-expanded") !== "true";
  nav.classList.toggle("is-open", open);
  menu.setAttribute("aria-expanded", String(open));
  menu.textContent = open ? "Close menu" : "Menu";
  if (open) nav.querySelector("a").focus();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && nav.classList.contains("is-open")) {
    closeMenu();
    menu.focus();
  }
});
document.addEventListener("keydown", (e) => {
  if (e.key !== "Tab" || !nav.classList.contains("is-open")) return;
  const links = [menu, ...nav.querySelectorAll("a")];
  if (e.shiftKey && document.activeElement === links[0]) {
    e.preventDefault();
    links.at(-1).focus();
  } else if (!e.shiftKey && document.activeElement === links.at(-1)) {
    e.preventDefault();
    menu.focus();
  }
});
nav.addEventListener("click", (e) => {
  if (e.target.closest("a")) closeMenu();
});
const toc = document.querySelector(".page-toc details"),
  compact = matchMedia("(max-width:1199px)");
function resizeToc() {
  toc.open = !compact.matches;
  document.querySelectorAll('.local-toc').forEach(n=>n.open=!compact.matches);
}
resizeToc();
compact.addEventListener("change", resizeToc);
document.querySelectorAll("pre:has(code)").forEach((pre) => {
  const code = pre.querySelector("code"),
    button = document.createElement("button");
  button.className = "code-copy";
  button.textContent = "Copy";
  button.setAttribute("aria-label", "Copy code");
  button.onclick = async () => {
    try {
      await navigator.clipboard.writeText(code.textContent);
      button.textContent = "Copied";
    } catch {
      button.textContent = "Select code to copy";
    }
    setTimeout(() => (button.textContent = "Copy"), 1800);
  };
  pre.append(button);
});
function markSection() {
  document.querySelectorAll(".page-toc a").forEach((a) => {
    if (a.hash === location.hash) a.setAttribute("aria-current", "location");
    else a.removeAttribute("aria-current");
  });
}
addEventListener("hashchange", markSection);
markSection();
