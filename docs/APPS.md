# Apps on the farm at launch

1. Titanium Tiiny Bot: /Users/sem/code/titanium-bot-lite
2. Story Lantern: github.com/webdevtodayjason/story-lantern
3. OneLane: github.com/webdevtodayjason/onelane (library)
4. Tiiny Bench: /Users/sem/code/tiiny/tiiny-bench (partially built; a manifest once it has a selfcheck and a release)

Each manifest says how its app takes a port, so `farm start <id> --port N` moves any app
without the CLI knowing it by name. Titanium Tiiny Bot takes `--port` and TiinyBench takes
`--serve`, both on the command line, so their manifests say `{"argv": "--port"}` and
`{"argv": "--serve"}`. Story Lantern reads `PORT`, so its manifest says `{"env": "PORT"}`.
OneLane is a library with nothing to start and no port, so its manifest says `null`, and
`--port` is refused rather than quietly ignored. An app that declares nothing gets
`TIINYAPP_PORT`, which is what the farm has always set.
