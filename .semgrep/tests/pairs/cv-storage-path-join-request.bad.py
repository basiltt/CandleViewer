import os
def f(request, root):
    return os.path.join(root, request.dataset)
