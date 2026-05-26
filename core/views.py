from django.shortcuts import render

from core.models import Evento


# Create your views here.
def tela_inicial(request):
    return render(request, 'index.html')

def lista_eventos(request):
    evento = Evento.objects.all()
    dados = {'eventos': evento}
    return render (request, 'evento.html', dados)