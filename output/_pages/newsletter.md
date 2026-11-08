---
permalink: /newsletter/
title: "Newsletter"
excerpt: "Die neuen Nachrichten von BriefBerlin – jeden Morgen im Postfach"
layout: single
---

## Der BriefBerlin-Newsletter

Jeden Morgen um 7 Uhr schicken wir dir eine E-Mail mit den neuen Nachrichten aus Berlin.
In der E-Mail steht: eine Überschrift, ein paar Sätze und ein Link zum ganzen Text.

- **Kostenlos.** Der Newsletter kostet nichts.
- **Einfach.** Die Nachrichten sind in einfachem Deutsch (Niveau A2 und B1).
- **Nur bei Neuigkeiten.** An Tagen ohne neue Nachrichten schicken wir keine E-Mail.
- **Jederzeit abmeldbar.** In jeder E-Mail ist ein Link zum Abmelden.

## Anmeldung

Du brauchst nur deine E-Mail-Adresse.

<div class="newsletter-signup">
{% if site.newsletter.signup_open == false %}
  <div class="notice--info" role="status">
    <p><strong>Die Anmeldung ist gerade geschlossen.</strong></p>
    <p>Der Newsletter ist vorübergehend nicht für neue Anmeldungen offen. Bitte versuche es später wieder.</p>
  </div>
{% else %}
  {% include brevo-signup-form.html %}
{% endif %}
</div>

Nach dem Abschicken schicken wir dir zuerst eine E-Mail.
Klicke darin auf den Link. Erst dann bekommst du den Newsletter.
Das nennt man Double Opt-in. So ist sichergestellt, dass wirklich du dich angemeldet hast.

Mehr in unserer [Datenschutzerklärung]({{ '/privacy/' | relative_url }}). Fragen? Schreib uns über die [Kontaktseite]({{ '/contact/' | relative_url }}).
