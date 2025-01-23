from django.shortcuts import render

def csrf_failure(request, reason=""):
    print(request.__dict__)
    return render(request, '403_csrf.html', {'reason': reason})