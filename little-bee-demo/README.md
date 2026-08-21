Little Bee — Web demo
This folder contains a single-page web demo of the "Little Bee" game ported from a Python/pygame prototype.

Files added here:

index.html — the complete web game (Canvas + WebAudio). Open this file in a browser or host using GitHub Pages.
.nojekyll — empty file to disable Jekyll processing on GitHub Pages.
How to use

Save these files to little-bee-demo/ and create the gh-pages branch (or push to your chosen Pages branch).
To publish the demo via GitHub Pages:
Go to the repository Settings → Pages.
Select the gh-pages branch and the root folder (/) as the source and save.
The site should appear at https://<your-username>.github.io/automatic-umbrella/little-bee-demo/ after a minute.
Alternatively, run locally by serving the folder (e.g., python -m http.server) and open index.html.

Controls

Space or Up Arrow: flap
F: fire stinger (short cooldown)
R: restart after Game Over
Esc: pause/resume
Persistence

Scores are stored using localStorage in your browser. Per-player top-10 scores and a global top-5 (by each player's best score) are shown on Game Over.

Notes

This is a direct Canvas port; the visuals are vector-drawn and sounds use WebAudio OscillatorNodes (procedural tones). No external assets are required.
If you want different hosting (root vs subfolder) or a different branch name, tell me and I can move the files.
