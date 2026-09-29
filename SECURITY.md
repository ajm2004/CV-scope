# Security policy

## Reporting a vulnerability

Please report security problems privately, not in a public issue: use
GitHub's **Report a vulnerability** button on the repository's Security tab
(private vulnerability reporting). Include the version or commit, what an
attacker can do, and the steps to reproduce it. You will get an answer within
a week; please allow time for a fix before disclosing it publicly.

## Deployment model

CV-Scope is designed to run on one computer, next to its cameras:

* The server binds to `127.0.0.1` by default and has **no login**. Anyone
  who can reach its port can see the cameras, change experiments and read the
  stored data. Before opening it to a network, put it behind a reverse proxy
  with authentication and TLS (`docs/guides/21-deploy-a-study.md`).
* Camera footage, recordings, the database and model weights stay in the data
  directory (`PATHSCOPE_DATA_DIR`, `./data` by default). Nothing is uploaded
  unless you configure a cloud vision-model provider for the Anomaly
  Assistant, which then receives the pictures of the events it describes
  (`docs/anomaly.md`).
* The optional recognition modules keep biometric templates and enrollment
  pictures encrypted; their keys live in `<data>/recognition/keys` (or
  `PATHSCOPE_RECOGNITION_KEY_DIR`). Access needs a recognition token with a
  role (`docs/recognition.md`).

## Never commit

The repository's `.gitignore` keeps these out, but check before you push a
fork: `.env` files, `*.key` files (licence issuer keys, template and media
keys), `license.json` licence files, the `data/` directory, recordings, camera
snapshots, and exports of events, scenes or recognition data from a real
site.
