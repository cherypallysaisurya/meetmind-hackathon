# How I evaluate retrieval today

- 200 labelled queries from the support team, refreshed every month.
- The main number is recall at ten: the answer agent reads the top ten chunks.
- No language model judge yet. Two people label each query; they agree on 91 percent of them.
- The labelled set is run after every nightly rebuild; a drop of more than two points blocks the release.
