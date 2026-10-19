# 官方插件：音乐观众

This is the official music-audience data package. It declares music-room personas, topics, and preferences; it does not by itself prove that the host can generate music-domain responses. Full domain behavior still requires a separate compatibility and behavior review.

The released 1.1.0 package declares its topics with the v2 vocabulary (`format_version: 2`, stable ids plus match labels and aliases) and gives each role a `topic_interests` mapping. The host owns matching, relevance thresholds and every send decision; the package only states what a role cares about. Its minimum host version is 0.5.0b3.
