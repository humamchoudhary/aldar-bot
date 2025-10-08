import pdfplumber

with pdfplumber.open("ilhancv.pdf") as pdf:
    text = ""
    for page in pdf.pages:
        text += page.extract_text()
    print(text)
