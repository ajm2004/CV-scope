---
title: Recognize an enrolled person and a registered vehicle
level: Advanced
time: 60 minutes
needs: A recognition licence, a camera that sees faces at close range, and the sample clips
summary: Unlock the licensed recognition modules, enroll one person with the guided live capture, register one vehicle, and build rules that fire only for them.
learn:
  - Install a licence and create the first administrator token
  - Enroll a person with the guided live capture, where each view is taken by itself
  - Add a second look so the person is recognized in glasses, a hat or other light
  - Check with the test bench whether recognition is good enough
  - Answer the bench when it asks, and enroll a new person from it
  - Register a vehicle plate and test the plate-format layer
  - Add a recognition condition to a rule and read the diagnostics
  - See the recognized name in the live view, the data and the recorded clips
  - Delete a profile and confirm that nothing biometric remains
pages: [Recognition, Test recognition, Models, Experiments, Hardware]
---

# Recognize an enrolled person and a registered vehicle

Everything CV-Scope does so far is anonymous. This guide switches on the
two licensed modules, face recognition of *enrolled* identities and vehicle
plate recognition, and shows how a rule can be limited to one enrolled person
or one registered plate. It uses a webcam or IP camera for the person, because
the faces in the sample clips are about 20 px tall, too small to identify.

Read `docs/recognition.md` first if you administer the installation: it
explains the licence model, the roles and what is stored.

## Step 1. Unlock the modules

1. Open **Recognition** in the sidebar. Without a licence it shows one page
   with both modules as **Not licensed**.
2. Ask the vendor for a licence. They will want the licensee name and, for a
   licence bound to this computer, the id shown under **This machine's id**.
3. Click **Create the first administrator token**. The token is shown once and
   stored in this browser; keep a copy. Everything on the Recognition pages
   needs such a token.
4. If the vendor's public key is not already configured, paste it under
   **Trust an issuer public key** and click **Trust key**.
5. Paste the licence JSON under **Install a licence file** and click
   **Validate and install**. Both modules now read **Licensed** and the
   sidebar shows **People**, **Vehicles**, **Recognition events** and
   **Settings**.

## Step 2. Install the models

1. Open **Models** and scroll to **Recognition models**.
2. Install **YuNet face detector** and **SFace face embeddings** (about 37 MB
   together, MIT and Apache-2.0 licences, CPU).
3. Install **YOLOv9-t licence plate detector (384 px)** and **CCT-S v2 global
   plate OCR** (about 13 MB, MIT). They need ONNX Runtime; the setup script
   installs it.
4. Open **Hardware**. The panel **Recognition modules: effect on camera
   capacity** estimates how many streams this computer can still process
   with recognition on. On the development machine the estimate dropped from
   about 10 streams to 4 at 10 processed frames per second.

## Step 3. Enroll a person with the guided capture

The guided capture works like enrolling a face on a phone: the person sits in
front of the camera, the screen asks for one thing at a time, and each view is
kept by itself. Nobody has to press a button per picture.

1. Open **Recognition → People**, type `Research Subject 001` as the display
   name and `E-001` as the reference id, then click **Create profile**.
2. The profile opens on the **Guided (live camera)** tab. Choose your camera
   and click **Start guided capture**. The camera picture appears in a circle
   with a ring around it, one segment per view.
3. Follow the instruction in large type above the circle. It changes as the
   person moves: *Look straight at the camera*, *Move a little closer*, *More
   light on the face, please*, *Move into the circle*, *Only one person in
   front of the camera, please*. When everything fits, it says **Hold still…**
   and the bar fills; a moment later the view is captured, its ring segment
   turns green and the next instruction appears.
4. The plan is five views: front, turn to your left, turn to your right, chin
   down (what a camera above the person sees) and chin up. An arrow inside the
   ring points the way. Afterwards you can add **Lighting** (change the light
   in the room, the capture waits until it really differs) and **Back of
   head**, which is kept as an appearance reference only and never produces a
   template.
5. Click **Finish and check quality**. The result shows the status, the
   quality, the views covered and how consistent the pictures are with each
   other. Five views of the development machine's test pattern gave quality
   0.87 and consistency 0.64. An enrollment with a missing front view, too few
   views or inconsistent pictures stays **insufficient** and is never matched.

Notes on the guided capture:

* The left, right, chin-down and chin-up views are judged **against this
  person's own front view**, so a camera mounted off to the side or a model
  that reads a different neutral pose does not make every picture wrong.
* If a different face appears halfway through, the capture is refused with
  *This does not look like the same person as the front view*.
* The camera is opened only while the capture runs and is shared with the
  live view; a running experiment keeps its camera, and the guided capture
  then uses that run's picture.
* **Single pictures** is the second tab: pick a view, capture one frame or
  upload a file, and read the same guidance. Use it for network cameras
  where nobody watches the screen, or to enroll from existing photographs.

## Step 4. Add another look

One capture session records the person as they are today. Recognition gets
steadier when the profile also holds the appearances they really turn up in.

1. Open the profile again. Above the capture tabs, the row of **Look** buttons
   shows `First enrollment`. Click **+ Add another look**, type a name such as
   `Glasses` and click **Start this look**.
2. Change the appearance for real: put the glasses on, the hard hat on, or move
   to the evening light. Run the guided capture again; the ring starts empty,
   because each look keeps its own views.
3. Click **Finish and check quality**. The summary now lists both looks with
   their own agreement and how well the new look matches the first enrollment.
   A look that does not match is reported as a problem, which is what stops
   someone else from being added by mistake.
4. Every look is used when matching, so the person is recognized either way.
   A look can be deleted on its own; **Re-enroll** still clears the whole
   profile and starts over.

## Step 5. Check that recognition actually works

Open **Recognition → Test recognition**. Nothing on this page is stored.

1. **Live camera**: pick the camera and click **Start live test**. Stand in
   front of it. Each face gets a box and a label: the name and the similarity
   when recognized, `? name` for a possible match, or *Unknown* or
   *Insufficient quality* with the reason. The label follows the person about
   four times a second.
2. Walk to where the camera really watches from. If the label turns into
   *Insufficient quality*, the face is too small, too dark or too blurred
   there: move the camera closer or raise the resolution rather than lowering
   the thresholds.
3. **A picture**: upload a photograph of the person, or take one frame from any
   camera, and read the ranked candidates with their similarity. On the
   development machine, the photograph a profile was enrolled from came back as
   *Recognized* at 1.00 against a Recognized threshold of 0.46.
4. **Enrollment check**: every profile is compared with its own pictures and
   with everyone else. Read the verdict and the advice column: *Only one look*
   points back to Step 4, *Only 2 of 3 views* to the missing views, and a
   *Mix-up risk* warns that two enrolled people are close enough to be
   confused, which is the moment to add views and looks for both.

### Teaching it while you test

While the live test runs it asks about the person on screen, at most once
every 20 seconds per person.

1. **Is this Research Subject 001?** Click **Yes, correct**. The verdict is
   recorded and, because *Keep the picture when I confirm a match* is ticked,
   that frame becomes an enrollment picture in the look **Live confirmations**.
   Confirm a few times in the light and the position of the real camera and
   the profile learns the site, not just the enrollment desk.
2. Click **No** when it is wrong. Say who it really is, and that person gets
   the picture instead; or choose **Not enrolled — register**. The verdict is
   kept either way, and the counts above the picture show how often the
   installation is right here.
3. A face nobody matches is not identified. The bench asks **Not recognized.
   Register this person?**; with their agreement, click **Register and teach
   the views**, type the name, and the guided capture runs in place on the same
   camera, asking for front, left, right, chin down and chin up. Close it and
   the test recognizes the new profile at once.
4. A picture that does not look like the profile is refused: *This face matches
   … only at 0.21*. Add it anyway only when you are certain; that override is
   written to the audit trail. None of this moves a threshold by itself, and it
   is not model training: it adds enrollment pictures, which is what makes the
   difference in practice.

## Step 6. Register a vehicle

1. Open **Recognition → Vehicles** and register plate `ABC12345` with the
   description `Site car` and the group `Staff`.
2. In **Test the plate format layer**, type `DXB 12S67` and click
   **Normalise**. With the `uae` format enabled in the settings it becomes
   `DXB12567` with one confusable substitution; with only `generic` it stays
   `DXB12S67`. Choose the formats of your site under **Settings → Plate
   recognition** and keep `generic` last.

## Step 7. Rules that fire only for them

1. Create an experiment for the camera that sees the person, with **Person**,
   and draw a zone `Zone A` covering the area where they will stand.
2. Add a rule: **WHEN** Person, **RECOGNITION** *Specific enrolled person* →
   tick `Research Subject 001`, **ENTERS** `Zone A`, mode **Remains in zone
   for…** more than `30` seconds, **CREATE EVENT** `Extended Zone A presence`.
3. Add a second rule with **RECOGNITION** *Anonymous person* and
   **COUNT AS** `Unknown visitor` to see the difference.
4. For vehicles, create an experiment on a camera with **Car** and **Truck**,
   draw a gate `Entrance Gate`, and add: **WHEN** Car, **PLATE** *Specific
   plate* → `ABC12345`, **CROSSES** `Entrance Gate`, **RECORD AS**
   `Vehicle Entry`.
5. Click **Save** and **Start**. A rule with a recognition condition needs
   the module to be licensed and enabled; otherwise it stays inactive and the
   experiment's **Resolved configuration** says so.

## Step 8. Watch the recognition happen

1. While the run is active, open **Recognition → Recognition events**. The
   **Diagnostics of active runs** panel lists every track: whether a face was
   detected, its quality and why a frame was rejected, how many observations
   were usable, the best frame, the candidate identity with its similarity
   and runner-up, and the result (*Not decided*, *Recognized*, *Possible
   match*, *Unknown*, *Insufficient quality*).
2. Open **Live**. Because this browser holds a recognition token, the video
   label reads `#12 person = Research Subject 001` and the panel **Recognized
   now** lists each track with its name and confidence. In the Scene Builder
   the live overlay shows the same name. A browser without a token sees the
   box and the anonymous id only, on the same stream.
3. When the person has stayed 30 seconds, the event `Extended Zone A presence`
   appears under **Data** with `entity: enrolled_person` in its context. The
   stored event holds the id only; the **Identity** column resolves it to the
   name for this browser, and the CSV, JSON and Parquet exports stay
   anonymous. The full recognition detail (similarity, quality, model version,
   camera, track, frame) is on the **Recognition events** page.
4. If the experiment records video, open the run's **Analysis → Video** tab
   (set **From entry to exit** on the experiment to get one clip per visit):
   the clips are listed with the event that started each one and play in
   place, and the events inside the clip jump the player to the moment. The
   **Watch** link on every event row in **Data** opens the same clip on the
   Video review page. Recorded video never has names drawn into it, whoever
   watches it.
5. For the vehicle, the diagnostics show the raw OCR of each read, the
   temporal consensus (`ABC12?45` becomes `ABC12345` once enough reads agree),
   the normalized plate and the registered vehicle; the crossing is recorded
   as `Vehicle Entry`.

## Step 9. Clean up like an administrator

1. **Recognition events**: filter, export as CSV (administrators only; the
   export is audited) or delete single events.
2. **Settings → Retention**: recognition events and unregistered plate reads
   are removed after the configured days.
3. **People**: open the profile and click **Delete profile**. The templates
   are removed at once and the encrypted enrollment images with them (or
   after the configured grace period).
4. **Settings → Audit trail** lists who did what: profile created, enrollment
   finalised, licence installed, export created, profile deleted.
5. **Settings → What this installation stores** (the ordinary Settings page)
   now lists the modules and their state, so the privacy list stays honest.

## Notes

* Faces smaller than the minimum size (40 px by default) and plates below
  14 px are never identified; the diagnostics say *Insufficient quality*.
  Move the camera closer or raise the resolution rather than lowering the
  thresholds far.
* The Recognized threshold, the margin to the runner-up and the number of
  observations before a decision are under **Settings → Advanced settings**.
  Calibrate them on your own site with a few known people.
* Unknown people always stay anonymous tracks. The module cannot search for
  people who were not enrolled and never infers age, gender or any other
  attribute.
* When recognition looks wrong on site, go to **Test recognition** before
  changing thresholds: it says whether the picture, the enrollment or the
  threshold is the problem.
