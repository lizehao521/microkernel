def mean(xs):
    if not xs:
        raise ValueError("xs 是空的")
    return sum(xs) / len(xs)
