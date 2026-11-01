# Kitsune user guide

Kitsune saves every version of your painting, so you can try ideas without being afraid of losing anything. You can see what changed between two versions, bring back part of an old one, and keep your layers along the way.

**Kitsune never makes art.** It doesn't paint or generate anything. Every image it saves is made of your own pixels.

## The basics

| Word | What it means |
| --- | --- |
| **Piece** | One artwork and its whole history. |
| **Version** | A saved moment of your painting. Versions are numbered v1, v2, v3 and so on. |
| **Branch** | A separate line of work for trying an idea, like a dusk palette. Your main work stays on `main`. |
| **Merge** | Combining two lines of work into one new version. |
| **Bring back** | Copying one part of an old version into your latest one. |

Saving a new version never overwrites an old one. Bring-backs, merges and palette variations all create new versions too, so your history stays intact.

## Two ways to use Kitsune

- **In the browser:** upload your versions and work on them visually. This is the easiest way to start.
- **From the command line:** use the `kitsune` command beside your paint app. This is quicker if you save often, and it can load old versions straight back into your file.

Both show the same history, so you can mix them freely.

**File types:** Kitsune reads PNG, JPG, Photoshop `.psd`, Krita `.kra` and OpenRaster `.ora`. Use your paint app's own file if you can, because that keeps your layers. Procreate, Clip Studio and GIMP files need exporting to PNG first, which saves a flat image without layers.

## Using the browser

### Start a piece

1. Open Kitsune, type a name for your piece, and click **Create**.
2. Click **Upload your first version**, choose your file, and click **Save version**. You can add a message saying what changed, or leave it blank.
3. Each time you've made progress, click **Upload version** at the top and do the same again.

New versions go on the branch shown in the **Branch** menu at the top, so check it before uploading.

### See what changed

Click a version on the timeline to view it, then click **Compare with previous**. To compare any two versions, click one and shift-click the other.

- **Slider** lets you drag between before and after.
- **Side by side** shows both, and you can scroll to zoom and drag to pan.
- **What changed** lists each changed area and how it changed.

### Bring back part of an old version

The old sky was better, but you want to keep today's figure:

1. Compare the old version with the latest version of your branch.
2. Under **What changed**, click **Bring back from v3** next to the area you want, and confirm.

To choose the area yourself, click **Select part of v3 by hand** and draw around it with your mouse, pen or finger. Check **See the result**, then click **Copy into a new version**.

Anything you drew later in that area stays, so a lantern you added to the sky isn't pasted over. The copied part goes back where it was in the old version, so it won't follow if your composition has moved.

### Try an idea on a branch

1. Click the version you want to start from, then click **Branch from here**.
2. Give it a name such as `dusk-palette` and click **Create**.
3. Choose that branch in the **Branch** menu, then upload your new versions as usual.

Your `main` branch doesn't change while you experiment.

### Merge your work together

1. Click **Merge…** at the top.
2. Under **Bring changes from**, choose the branch you want to bring in. Under **into**, choose where it should go.
3. Click **Check** to see what would happen.
4. If both branches changed the same area, choose which side to keep for each one.
5. Click **Merge into main** (the button names your chosen branch).

If both versions are Krita files, the merge happens layer by layer inside the file. If both branches changed the same layer, you get both copies, plus an extra layer showing where they overlap, so you can settle it in Krita.

### Get back lost Krita layers

If a newer version lost layers you still want, open **Merge…** and choose the older version under **Layers from an older version**. Everything in your latest version stays as it is, and the missing layers return to where they sat.

Both versions must be Krita files made of plain paint layers. If a file uses groups, masks or blend modes, Kitsune won't do this, so use a bring-back instead.

### Try palettes

Click a version, then **Explore palettes…**. Type a direction like *warmer* or *darker*, or leave it blank to try three suggestions. Each result is your own painting with its colors shifted, on its own branch. Click **Keep** or **Discard** on each one. Discarded branches are hidden, not deleted.

### Add notes and client feedback

Below each version, in **Notes**, you can type or record why something changed. Choose **My note** or **Client feedback** to say who it's from. Notes are pinned to that version and show up in search.

### Find an old version

Use the search bar above the timeline and describe what you're looking for, like *before I changed the sky*. It searches your messages and notes, plus version descriptions and changed areas.

### Other tools

- **Assistant:** ask for a few steps at once, like *take the sky from v4, keep today's figure, and warm it to match*. Each step is shown as it runs, and the results go on a new branch.
- **Story:** turns your history into a write-up of your process for a portfolio.
- **Download with layers:** gets the full file back for any version that has one.
- **Private:** tick this at the top to keep captions and search on the project's own self-hosted model. Region naming still uses the hosted service.
- **Delete this version:** only appears on the latest version of a branch. It removes the version permanently, and it won't work if later work is built on that version.

## Using the command line

### Set it up

You need Python 3.11 or newer. Install the `kitsune` command once:

```bash
pip install "git+https://github.com/janhavitupe/kitsune.git#subdirectory=cli"
```

Then open a terminal in the folder that holds your painting, and connect the painting to Kitsune. Do this once per painting:

```bash
kitsune init forest.kra --backend https://your-kitsune-server --web https://your-kitsune-site
```

If you run Kitsune on your own computer, leave out `--backend` and `--web`.

### Daily routine

```bash
kitsune commit -m "warmer sky"   # after each save in your paint app
kitsune log                      # list your versions
```

Leave out `-m` and Kitsune writes a message for you. To save a version automatically every time you save your file, run `kitsune watch` and leave it running. Press Ctrl+C to stop it.

### Common commands

| To do this | Run this |
| --- | --- |
| Check for unsaved changes | `kitsune status` |
| See every branch's versions | `kitsune log --all` |
| See what changed in the last version | `kitsune diff` |
| Compare two versions | `kitsune diff v3 v5` |
| Load an old version into your file | `kitsune checkout v3` |
| Save an old version as a separate file | `kitsune checkout v3 -o old.kra` |
| Bring back one area | `kitsune pick "sky" --from v3` |
| Create a branch from a version | `kitsune branch dusk --from v2` |
| Move to a branch | `kitsune switch dusk` |
| See your branches | `kitsune branch` |
| Merge a branch into your current one | `kitsune merge dusk` |
| Choose sides in a merge conflict | `kitsune merge dusk --take 0=source,1=target` |
| Get back lost Krita layers | `kitsune merge v4` |
| Add a note | `kitsune note "client wants dusk" --client` |
| Search your history | `kitsune search "before the dusk sky"` |
| Open this piece in the browser | `kitsune open` |
| See every command | `kitsune --help` |

Use the area names exactly as `kitsune diff` prints them when you run `kitsune pick`.

`checkout`, `switch` and `merge` can change your file on disk. **Reload it in your paint app afterwards**, or you'll be looking at the old picture.

### Going back to an old version

```bash
kitsune checkout v3
```

Reload the file, paint if you like, then run `kitsune commit` to carry on from that point. Your later versions are all still there.

## Keeping your layers

Each version you save from a `.psd`, `.kra` or `.ora` file is stored whole, with its layers. `checkout` and `switch` put back exactly the file you saved.

Versions Kitsune builds from pixels, like bring-backs and palette variations, are flat images. Krita merges keep layers. If your tracked file has layers and you load a flat version, Kitsune leaves your file alone rather than flatten it. You can still save the flat version elsewhere:

```bash
kitsune checkout v6 -o flat-version.png
```

## If something goes wrong

| What you see | What to do |
| --- | --- |
| "The file has changes that aren't committed" | Run `kitsune commit` first. Or add `--force` to throw those changes away, or use `-o` to write the old version to another file. |
| "Commit your changes first" | Run `kitsune commit`, then try `kitsune pick` again. |
| `kitsune commit` didn't make a version | Your file hasn't changed. Save it in your paint app first. |
| "already has everything from…" | That branch is already part of this one, so there's nothing to merge. |
| "already has every layer from v4" | No layers are missing. To copy back painted areas, use a bring-back. |
| "Both versions need to be Krita files to merge their layers" | Only Krita layers can be merged from an older version. For other files, use a bring-back. |
| "can't be merged layer by layer" | The file uses groups, masks or blend modes. Use a bring-back. |
| The picture didn't change after `checkout`, `switch` or `merge` | Reload the file in your paint app. |
| A new version shows "Analyzing changes…" | Kitsune is still working it out in the background, so give it a moment. |
| Areas are called "top-left area" and not "sky" | Kitsune names areas by position when its AI models aren't available. Everything still works. |
| `kitsune` can't connect | Check your internet connection and the server address you gave `kitsune init`. A hosted server can take a moment to respond. If you run Kitsune on your own computer, make sure it's started. |

If you overwrite your tracked layered file by loading a version, the previous file is kept at `.kitsune/before-load.kra` (or `.psd`, `.ora`), and only the most recent one is kept.

## AI features are optional

Saving, comparing, branching, merging and bringing back all work without AI. When the models are on, they read your work to name areas, write messages, transcribe notes, find versions and plan assistant steps. When they're off, Kitsune falls back to simpler methods, like naming areas by position.
