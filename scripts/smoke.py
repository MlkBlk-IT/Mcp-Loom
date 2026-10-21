from loom import anchors, compress

s = (
    "exit_code: 0\n"
    "error: fail https://a.example.com/v1\n"
    r"path C:\Temp\x.txt" "\n"
    "never print secrets\n"
    "port 8080\n"
    "v1.2.3\n"
)

anchor, chunks = compress.build_anchor(s)
cov = anchors.coverage(anchors.extract(s), anchor)
print("anchor chars :", len(anchor))
print("coverage      :", cov["coverage"])
print("missing       :", cov["missing"])
print("chunks        :", len(chunks))
print("--- anchor ---")
print(anchor)
