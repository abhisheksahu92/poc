# from your existing handler
with open(r"C:\Users\SAHUAX19\Documents\page_1.png", "rb") as f:
    img_bytes = f.read()

poly = [3.2742, 1.5965, 5.7768, 1.5991, 5.7766, 1.8248, 3.274, 1.8221]
buf = highlight_image_stream(img_bytes, poly)
# send `buf` as response body, or write to disk:
with open("out_highlighted.png", "wb") as o:
    o.write(buf.getvalue())