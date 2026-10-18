/* ember/quest.js: "Weekend quest" tab. The printable Quest Card. */
(() => {
  "use strict";
  const FL = window.FL;
  const { $, h, state } = FL;

  function questCard(q, name, forPrint) {
    return h("article", { class: "quest", id: forPrint ? null : "questCard" },
      h("div", { class: "quest-head" },
        h("b", { text: "This week" }),
        h("div", { class: "quest-meta" }, h("b", { text: `${q.duration_minutes} min` }), h("span", { text: FL.COST[q.cost] || FL.cap(q.cost) }))),
      h("div", { class: "quest-body" },
        h("div", {}, h("h3", { text: q.title }), h("p", { class: "grows", text: `Grows: ${q.theme_name}` })),
        h("p", { text: q.why_this }),
        h("div", {}, h("h4", { text: "You will need" }), h("ul", { class: "need" }, (q.materials || []).map((m) => h("li", { text: m })))),
        h("div", {}, h("h4", { text: "Steps" }), h("ol", { class: "how" }, (q.steps || []).map((s) => h("li", { text: s })))),
        h("div", { class: "split" },
          h("div", {}, h("h4", { text: `${name} leads` }), h("p", { text: q.child_role })),
          h("div", {}, h("h4", { text: "You help by" }), h("p", { text: q.parent_role }))),
        h("p", { class: "key" }, h("b", { text: "Ask while you work: " }), q.conversation_prompt),
        h("p", { class: "key" }, h("b", { text: "Done when: " }), q.success_looks_like),
        q.safety_note && h("p", { class: "safe" }, h("b", { text: "Keep safe: " }), q.safety_note)),
      !forPrint && h("div", { class: "quest-foot" },
        h("button", { class: "btn", type: "button", onclick: printQuest }, FL.icon("print"), "Print this card"),
        h("span", { text: "Prints just the card, so the activity happens away from the screen." })));
  }

  function printQuest() {
    const r = state.report;
    if (!r || !r.quest) return;
    $("#printRoot").replaceChildren(questCard(r.quest, r.child, true));
    document.body.classList.add("printing");
    window.print();
  }
  window.addEventListener("afterprint", () => {
    document.body.classList.remove("printing");
    $("#printRoot").replaceChildren();
  });

  FL.registerSection({
    id: "quest", order: 2, label: "Weekend quest",
    title: () => "This week's quest",
    desc: (r) => `One offline activity built from what ${r.child} is most drawn to.`,
    render: (r) => r.quest
      ? questCard(r.quest, r.child, false)
      : FL.emptyCard(`No weekend quest yet. Choose Analyse videos and Ember will plan one activity from what ${r.child} has been watching.`),
  });
})();
