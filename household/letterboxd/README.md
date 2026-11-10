# Household Letterboxd ratings

From Letterboxd's own data export (Settings > Data), 2026-11-10: `ratings.csv`, `watched.csv` and `likes/films.csv` only. These ratings are already public on the profile; reviews and diary entries are left out.

`movie_night.taste` reads this folder for the full rating history, since Letterboxd only serves the newest 72 films to scripts. Newer ratings come from the live profile every day, so this only needs refreshing if older ratings change.
