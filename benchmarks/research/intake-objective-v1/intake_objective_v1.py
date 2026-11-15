#!/usr/bin/env python3
"""Intake objective v1: long synthetic dictations whose main ask is known by construction.

    python benchmarks/research/intake-objective-v1/intake_objective_v1.py generate

The protocol, metrics and pass criteria are in PROTOCOL.md next to this file. Every case is
one hand-written main request (a base) buried among k micro-context blocks drawn from a
hand-written pool, in one of five scenario families. The gold (main ask, supporting
sentences, every ask) is carried as character spans of the generated text.

Odd-numbered bases are the dev split, even-numbered bases the test split. Marker and
restatement phrasings for the test split come from ``codex_phrasings.json``, written by Codex
from the brief stored in that file; the dev split uses the phrasings below. Generation is
stdlib only and deterministic; the checks that need ``lcc`` (sentence split, roles) live in
``tests/test_intake_objective_bench.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CASES_PATH = HERE / "cases.json"
CODEX_PATH = HERE / "codex_phrasings.json"
SEED = 20261116
VERSION = "intake-objective-v1"
FAMILIES = ["marker", "recurrence", "restate", "first", "bare"]
LENGTHS = [4, 8, 16]

# --- bases -----------------------------------------------------------------------------------
# One main ask (the first sentence), up to two supporting sentences, three later mentions of
# the topic that ask for nothing (recurrence family), and a restatement body that follows a
# recap phrasing (restate family). Asks start with a word that may be lowercased after a
# marker; mentions and supporting sentences hold no request.
BASES: list[dict[str, Any]] = [
    {"id": "pt01", "lang": "pt",
     "ask": "Arruma o checkout que trava quando o cliente paga com Pix.",
     "support": ["Desde sexta já foram umas trinta vendas perdidas por causa disso.",
                 "O cartão de crédito tá funcionando normal, o problema é só no Pix."],
     "recur": ["Aliás, hoje cedo mais um cliente reclamou que o Pix ficou carregando no checkout.",
               "E o pessoal do suporte já tá cansado de explicar esse travamento do Pix.",
               "Fiquei pensando que o checkout com Pix é o que mais vende no fim de semana."],
     "restate": "arruma o checkout do Pix, que é o que tá doendo no bolso."},
    {"id": "pt02", "lang": "pt",
     "ask": "Migra o banco do SQLite pro Postgres antes do lançamento da semana que vem.",
     "support": ["Com mais de dez usuários ao mesmo tempo o SQLite já começa a travar a escrita.",
                 "O backup atual fica numa pasta do próprio servidor."],
     "recur": ["Ontem o SQLite travou de novo quando três pessoas salvaram juntas.",
               "O cliente perguntou se no lançamento vai aguentar o movimento todo, e eu fiquei "
               "sem resposta.",
               "Vi um vídeo sobre Postgres em produção e fiquei mais tranquilo com a troca."],
     "restate": "o banco tem que sair do SQLite e ir pro Postgres antes do lançamento."},
    {"id": "pt03", "lang": "pt",
     "ask": "Corrige o relatório mensal de vendas, que tá somando o imposto duas vezes.",
     "support": ["O contador viu a diferença ontem e ficou preocupado com a declaração."],
     "recur": ["Lembrei agora que o relatório de outubro também saiu com o imposto estranho.",
               "O contador mandou mensagem de novo falando das vendas de setembro.",
               "Esse relatório mensal é o que o sócio olha toda segunda de manhã."],
     "restate": "corrige o imposto em dobro no relatório mensal de vendas."},
    {"id": "pt04", "lang": "pt",
     "ask": "Quero que você conserte o login com Google no aplicativo, que parou depois da "
            "última atualização.",
     "support": ["Quem entra com e-mail e senha consegue acessar normalmente."],
     "recur": ["Uma cliente mandou print da tela de erro do Google hoje de manhã.",
               "Na loja de aplicativos já apareceu uma avaliação de uma estrela falando do login.",
               "A última atualização do aplicativo foi aquela que mexeu nas bibliotecas de "
               "autenticação."],
     "restate": "preciso do login com Google funcionando de novo no aplicativo."},
    {"id": "pt05", "lang": "pt",
     "ask": "Investiga por que a emissão automática de nota fiscal tá falhando desde o dia "
            "primeiro.",
     "support": ["A prefeitura mudou alguma coisa no sistema dela, mas ninguém avisou a gente.",
                 "Por enquanto a Bia tá emitindo tudo na mão."],
     "recur": ["A Bia comentou que já tem quarenta notas paradas esperando emissão.",
               "Se a nota fiscal não sai, o cliente não paga, então isso pesa no caixa do mês.",
               "Vi no grupo de contadores que outras empresas também tão com problema na "
               "prefeitura."],
     "restate": "investiga essa falha da nota fiscal automática."},
    {"id": "pt06", "lang": "pt",
     "ask": "Verifica por que o backup do servidor não roda há uma semana.",
     "support": ["O último arquivo de backup que eu achei é do dia três."],
     "recur": ["Fiquei com medo lembrando daquela vez que o disco do servidor queimou.",
               "Se acontecer alguma coisa agora, a gente perde uma semana inteira de cadastros "
               "sem backup.",
               "O provedor de hospedagem até oferece backup, mas é pago à parte."],
     "restate": "verifica o backup do servidor antes que dê problema."},
    {"id": "pt07", "lang": "pt",
     "ask": "Implementa a integração do agendamento da clínica com o WhatsApp, pra confirmação "
            "de consulta sair sozinha.",
     "support": ["Hoje a recepcionista confirma uma por uma e perde a manhã inteira nisso.",
                 "A clínica já tem o número comercial verificado."],
     "recur": ["A recepcionista me disse que metade das faltas é de quem esqueceu a consulta.",
               "O dono da clínica comentou de novo da confirmação pelo WhatsApp na reunião de "
               "ontem.",
               "Tem clínica concorrente que já manda lembrete automático de consulta."],
     "restate": "implementa a confirmação de consulta pelo WhatsApp."},
    {"id": "pt08", "lang": "pt",
     "ask": "Quero o site da clínica carregando rápido no celular, porque hoje leva quase dez "
            "segundos.",
     "support": ["As fotos da equipe são enormes, cada uma com vários megas."],
     "recur": ["Testei no meu celular no estacionamento e o site da clínica ficou na tela branca.",
               "A maioria dos pacientes chega pelo celular, pelo que mostrou o relatório do "
               "Google.",
               "Aquelas fotos da equipe foram tiradas com câmera profissional, por isso pesam "
               "tanto."],
     "restate": "quero o site da clínica rápido no celular."},
    {"id": "pt09", "lang": "pt",
     "ask": "Cria uma sincronização da planilha de estoque com o sistema da loja, pra parar de "
            "vender produto que acabou.",
     "support": ["Semana passada vendemos quatro jaquetas que não existiam mais."],
     "recur": ["Hoje mesmo apareceu outro pedido de jaqueta que não tinha no estoque.",
               "A gerente da loja mexe na planilha toda noite, então os dados de estoque "
               "existem.",
               "Devolver dinheiro de pedido sem estoque tá queimando a reputação da loja."],
     "restate": "cria essa sincronização do estoque com a loja."},
    {"id": "pt10", "lang": "pt",
     "ask": "Corrija a cobrança recorrente, que tá cobrando alguns clientes duas vezes no mesmo "
            "mês.",
     "support": ["Já foram três reclamações essa semana e uma ameaçou abrir disputa no cartão.",
                 "Parece que acontece quando o cartão é recusado na primeira tentativa."],
     "recur": ["Outro cliente acabou de mandar e-mail falando da cobrança em dobro.",
               "Tive que estornar mais uma cobrança hoje cedo.",
               "Se isso chega no Reclame Aqui, a gente perde um monte de cliente recorrente."],
     "restate": "corrija a cobrança em dobro dos clientes recorrentes."},
    {"id": "pt11", "lang": "pt",
     "ask": "Escreve a proposta do aplicativo da padaria com o escopo e o prazo, porque eles "
            "querem fechar até sexta.",
     "support": ["O dono quer pedido pelo celular e retirada no balcão."],
     "recur": ["O dono da padaria me ligou de novo perguntando da proposta.",
               "Passei na padaria de manhã e o balcão tava lotado, dá pra entender por que eles "
               "querem o aplicativo.",
               "Eles comentaram que a padaria do outro lado da rua já tem pedido pelo celular."],
     "restate": "escreve a proposta da padaria até sexta."},
    {"id": "pt12", "lang": "pt",
     "ask": "Cria o dashboard de vendas do time comercial, com meta e resultado por vendedor.",
     "support": ["Hoje eles juntam tudo numa planilha na sexta à tarde."],
     "recur": ["O gerente comercial perguntou de novo quando sai o dashboard.",
               "Na reunião de vendas ninguém sabia dizer quem tinha batido a meta.",
               "Aquela planilha de sexta à tarde tem fórmula quebrada pra todo lado."],
     "restate": "cria o dashboard do time de vendas com a meta por vendedor."},
    {"id": "pt13", "lang": "pt",
     "ask": "Investigue por que os e-mails de confirmação de pedido tão caindo no spam.",
     "support": ["Começou depois que a gente trocou o provedor de e-mail."],
     "recur": ["Uma cliente achou o e-mail de confirmação no spam e mandou print.",
               "O suporte tá recebendo ligação de gente achando que o pedido não foi feito.",
               "O provedor novo de e-mail era mais barato, mas talvez tenha sido uma troca ruim."],
     "restate": "investigue os e-mails de confirmação que caem no spam."},
    {"id": "pt14", "lang": "pt",
     "ask": "Revisa as permissões do sistema, porque o estagiário tá vendo os dados financeiros "
            "da empresa.",
     "support": ["Ele mesmo me avisou, ainda bem, mas isso não podia acontecer."],
     "recur": ["Fiquei pensando em quantas outras pessoas conseguem ver o financeiro.",
               "O estagiário entrou faz duas semanas e já tinha acesso a tudo.",
               "Com a lei de proteção de dados, um vazamento do financeiro dá multa pesada."],
     "restate": "revisa as permissões pra ninguém de fora ver o financeiro."},
    {"id": "pt15", "lang": "pt",
     "ask": "Migra os contatos antigos do CRM velho pro novo, com o histórico de cada cliente.",
     "support": ["São uns quatro mil contatos espalhados em duas contas."],
     "recur": ["O time de vendas tá trabalhando às cegas sem o histórico dos clientes antigos.",
               "O CRM velho vence no fim do mês e a assinatura não vai ser renovada.",
               "Uma vendedora ligou pra um cliente antigo achando que era contato novo."],
     "restate": "migra os contatos do CRM velho com o histórico."},
    {"id": "pt16", "lang": "pt",
     "ask": "Escreva testes automatizados pro fluxo de cadastro, porque toda atualização quebra "
            "alguma coisa nele.",
     "support": ["Na última versão o campo de CPF parou de aceitar ponto e traço."],
     "recur": ["De novo hoje alguém reclamou que não conseguiu terminar o cadastro.",
               "Cada vez que o cadastro quebra a gente só descobre pelo cliente.",
               "O campo de CPF já quebrou três vezes este ano."],
     "restate": "escreva os testes do cadastro antes da próxima versão."},
    {"id": "pt17", "lang": "pt",
     "ask": "Adiciona a versão em inglês do aplicativo, porque o cliente vai abrir uma filial em "
            "Londres.",
     "support": ["Os textos já tão todos num arquivo separado."],
     "recur": ["O cliente mandou a lista das telas que mais aparecem pros usuários de Londres.",
               "Pensei em usar tradução automática, mas o inglês ficaria estranho em alguns "
               "botões.",
               "A filial em Londres inaugura em março, se nada mudar."],
     "restate": "adiciona o inglês no aplicativo antes da filial de Londres."},
    {"id": "pt18", "lang": "pt",
     "ask": "Corrige o bot de atendimento, que tá informando o horário de funcionamento errado.",
     "support": ["Ele diz que a loja fecha às dezoito, mas agora a gente fecha às vinte."],
     "recur": ["Ontem um cliente deixou de vir porque o bot disse que a loja já tinha fechado.",
               "O horário mudou em outubro e ninguém lembrou de mexer no bot.",
               "O bot de atendimento responde quase metade das conversas do dia."],
     "restate": "corrige o horário que o bot de atendimento informa."},
    {"id": "pt19", "lang": "pt",
     "ask": "Configura a renovação automática do certificado SSL do site da loja, que vence "
            "daqui a quatro dias.",
     "support": ["Se vencer, o navegador mostra aquele aviso vermelho e ninguém compra."],
     "recur": ["Recebi outro e-mail automático avisando que o certificado tá perto de vencer.",
               "Ano passado o certificado venceu num sábado e a loja ficou o fim de semana fora.",
               "O site da loja é a única coisa que vende de madrugada."],
     "restate": "configura a renovação do certificado SSL antes de vencer."},
    {"id": "pt20", "lang": "pt",
     "ask": "Gera o relatório de comissões em PDF, por vendedor, pro fechamento do mês.",
     "support": ["Hoje o financeiro calcula tudo na mão e sempre dá alguma diferença."],
     "recur": ["Um vendedor reclamou que a comissão dele veio menor do que devia.",
               "O fechamento do mês é dia trinta e o financeiro já tá apertado.",
               "Na outra empresa em que eu trabalhei, o relatório de comissões saía sozinho."],
     "restate": "gera o PDF de comissões por vendedor pro fechamento."},
    {"id": "en01", "lang": "en",
     "ask": "Fix the password reset emails, because customers say they never arrive.",
     "support": ["It started after we moved the domain to the new mail provider."],
     "recur": ["Another customer wrote in this morning saying the reset email never came.",
               "Support spent half of Tuesday resetting passwords by hand.",
               "The new mail provider was cheaper, but I'm starting to regret the switch."],
     "restate": "fix the password reset emails."},
    {"id": "en02", "lang": "en",
     "ask": "Investigate the Stripe webhook, because paid orders are stuck as pending.",
     "support": ["The money lands in the account, but the order page never updates.",
                 "We have about sixty orders in that state since Friday."],
     "recur": ["Two more customers emailed asking why their paid order still says pending.",
               "I had a look at the Stripe dashboard and the webhook shows a wall of red.",
               "Our warehouse can't ship anything that's stuck as pending."],
     "restate": "investigate why the Stripe webhook leaves paid orders pending."},
    {"id": "en03", "lang": "en",
     "ask": "Migrate the cron jobs to the queue worker before we switch servers next week.",
     "support": ["Right now three of them overlap at midnight and the database chokes."],
     "recur": ["The midnight cron overlap took the site down for ten minutes again last night.",
               "The new server doesn't even have cron configured yet.",
               "The queue worker has been sitting there idle since we set it up in the spring."],
     "restate": "migrate those cron jobs onto the queue worker."},
    {"id": "en04", "lang": "en",
     "ask": "Can you fix the product search so that accented words return results again?",
     "support": ["Half our catalogue has French and Portuguese names."],
     "recur": ["A customer typed crème brûlée in the search box and got nothing back.",
               "Our sales report shows a weird dip on the accented products.",
               "The search box is the first thing people use on the product page."],
     "restate": "fix the accent problem in the product search."},
    {"id": "en05", "lang": "en",
     "ask": "Build the online booking page for the physio clinic, with slots pulled from their "
            "calendar.",
     "support": ["They currently take every booking over the phone.",
                 "The clinic opens a second room in January."],
     "recur": ["The physio called again asking when patients can book online.",
               "Their receptionist misses calls whenever she's with a patient.",
               "The clinic calendar is already shared with all three physios."],
     "restate": "build the booking page for the physio clinic."},
    {"id": "en06", "lang": "en",
     "ask": "Investigate the memory leak in the API server, since it gets restarted every night.",
     "support": ["Memory climbs steadily from about two hundred megabytes to four gigabytes."],
     "recur": ["The API server got killed at three in the morning again.",
               "I noticed memory climbing faster on the days with more traffic.",
               "The nightly restart hides it, but one day the API server is going to fall over "
               "at lunch."],
     "restate": "investigate the memory leak in the API server."},
    {"id": "en07", "lang": "en",
     "ask": "Fix the Android app crash that happens when people open the camera on Android 15.",
     "support": ["iPhones are fine, and older Android versions are fine too."],
     "recur": ["Another one star review mentioned the camera crash on a new Pixel.",
               "The store shows Android 15 users are now a third of our installs.",
               "The camera is how people scan their membership cards, so the crash blocks entry."],
     "restate": "fix the camera crash on Android 15."},
    {"id": "en08", "lang": "en",
     "ask": "Write the onboarding docs for the new developer who starts on Monday.",
     "support": ["Last time it took two weeks before the new hire could run the project."],
     "recur": ["The new developer already emailed asking which laptop setup we use.",
               "Half of what matters about the project lives only in my head.",
               "Last onboarding, I spent a whole afternoon explaining the deploy steps out loud."],
     "restate": "write the onboarding docs before Monday."},
    {"id": "en09", "lang": "en",
     "ask": "Add rate limiting to the public API before the partner launch.",
     "support": ["One script hit us with forty thousand requests in an hour last week."],
     "recur": ["That same script came back last night and hammered the public API for twenty "
               "minutes.",
               "The partner expects heavy traffic from day one of the launch.",
               "Our hosting bill jumped because of those requests."],
     "restate": "add rate limiting to the public API."},
    {"id": "en10", "lang": "en",
     "ask": "Fix the invoice PDFs, because the VAT line shows the wrong rate for UK customers.",
     "support": ["The total is right, it's only the line breakdown that's wrong."],
     "recur": ["An accountant at one of our UK customers flagged the VAT line again.",
               "Every wrong invoice means a credit note and a fresh copy.",
               "The invoice template was last touched when we added the new logo."],
     "restate": "fix the VAT rate on the invoice PDFs."},
    {"id": "en11", "lang": "en",
     "ask": "Add two-factor authentication to the admin panel.",
     "support": ["Five people have admin access and two of them reuse passwords everywhere."],
     "recur": ["I read about another agency whose admin panel got taken over last month.",
               "One of the admin accounts logged in from a country none of us has visited.",
               "The admin panel controls refunds, so a break-in there costs real money."],
     "restate": "add two-factor authentication to the admin panel."},
    {"id": "en12", "lang": "en",
     "ask": "Please fix the analytics dashboard, which counts every session twice.",
     "support": ["The numbers doubled the same day we added the new tracking script."],
     "recur": ["Marketing presented the doubled session numbers to the board without noticing.",
               "The tracking script went in alongside the cookie banner.",
               "I don't trust a single chart on that analytics dashboard right now."],
     "restate": "fix the double counted sessions on the analytics dashboard."},
    {"id": "en13", "lang": "en",
     "ask": "Move the uploaded images from the server disk to object storage before the disk "
            "fills up.",
     "support": ["The disk is at ninety one percent and it grows about a percent a week."],
     "recur": ["Got another alert this morning about the server disk.",
               "Most of those uploaded images are huge product photos nobody resized.",
               "Object storage would cost a few pounds a month for all of it."],
     "restate": "move the images off the server disk to object storage."},
    {"id": "en14", "lang": "en",
     "ask": "Investigate why the CSV import drops every row that has a comma inside a field.",
     "support": ["The import says it succeeded, so nobody noticed the missing rows for weeks."],
     "recur": ["A client found out their CSV import had lost about a tenth of the addresses.",
               "Those missing rows were mostly companies with a comma in their name.",
               "The import screen still shows a green success message every time."],
     "restate": "investigate the CSV import that drops rows with commas."},
    {"id": "en15", "lang": "en",
     "ask": "Update the framework to the next major version before security support ends in "
            "March.",
     "support": ["We're two major versions behind and every plugin warns about it."],
     "recur": ["Another security advisory came out for our framework version this week.",
               "Two plugins already stopped shipping fixes for the old framework.",
               "March sounds far away, but the last major version jump took us a month."],
     "restate": "update the framework before security support ends."},
    {"id": "en16", "lang": "en",
     "ask": "Fix the calendar sync, because it creates duplicate appointments every time a "
            "patient reschedules.",
     "support": ["The clinic sees the same patient twice on the board and books over the slot."],
     "recur": ["Reception called about another duplicate appointment this morning.",
               "A patient turned up for a slot that the calendar had already given away.",
               "The calendar sync runs every five minutes, so the duplicates pile up fast."],
     "restate": "fix the duplicate appointments from the calendar sync."},
    {"id": "en17", "lang": "en",
     "ask": "Check why the landing page form stopped sending leads to the client's CRM.",
     "support": ["The form shows a thank you message, but nothing reaches the CRM."],
     "recur": ["The client asked why their CRM had zero new leads this week.",
               "They're paying for ads that send people to that landing page every day.",
               "The last lead in the CRM came in on the day we changed the form fields."],
     "restate": "check the landing page form that stopped sending leads."},
    {"id": "en18", "lang": "en",
     "ask": "Build a staging environment that mirrors production, so we stop testing on live "
            "data.",
     "support": ["Last month a test order went out to a real customer."],
     "recur": ["Someone tested a discount code on production again yesterday.",
               "Every release we cross our fingers because there's nowhere safe to try it first.",
               "Production runs on two servers and a managed database."],
     "restate": "build the staging environment that mirrors production."},
    {"id": "en19", "lang": "en",
     "ask": "Fix the nightly report email, which goes out with yesterday's section empty.",
     "support": ["The data is in the database, it just doesn't make it into the email."],
     "recur": ["The sales director forwarded the empty nightly report to me again.",
               "That report email is the first thing the directors read every morning.",
               "It broke around the time the database moved to the new timezone setting."],
     "restate": "fix the empty section in the nightly report email."},
    {"id": "en20", "lang": "en",
     "ask": "Make the settings page readable in dark mode, because the text is almost "
            "invisible there.",
     "support": ["Light mode is fine, and most of the other pages look right in dark mode."],
     "recur": ["A user sent a screenshot of the settings page where you can barely read "
               "anything.",
               "Most of our users have dark mode on, according to the analytics.",
               "Accessibility-wise, that settings page contrast probably fails the guidelines."],
     "restate": "fix the dark mode contrast on the settings page."},
]  # fmt: skip

# --- block pool ------------------------------------------------------------------------------
# Micro-contexts on one topic each, of four kinds. Only errand blocks hold gold asks (the
# indexes in "asks"): a request to the assistant of lower stakes. Thinking aloud and asides to
# someone in the room may read as requests to a cue-word parser, but they ask the assistant for
# nothing.
POOL: dict[str, list[dict[str, Any]]] = {
    "pt": [
        {"id": "ptN01", "kind": "narrative", "asks": [], "s": [
            "Hoje o trânsito tava um caos por causa da chuva.",
            "Levei quase uma hora pra fazer um trajeto de vinte minutos.",
            "Ainda bem que deu tempo de tomar um café antes da reunião."]},
        {"id": "ptN02", "kind": "narrative", "asks": [], "s": [
            "Ontem fui no aniversário do meu sobrinho.",
            "Ele fez sete anos e ganhou uma bicicleta azul.",
            "A festa foi num salão perto de casa, bem tranquila."]},
        {"id": "ptN03", "kind": "narrative", "asks": [], "s": [
            "Enfim, a academia nova perto do escritório inaugurou essa semana.",
            "Fui lá na hora do almoço e tava vazia.",
            "Os aparelhos são novos e o vestiário é bem limpo."]},
        {"id": "ptN04", "kind": "narrative", "asks": [], "s": [
            "O notebook tá esquentando bastante esses dias.",
            "Acho que é a poeira no ventilador, porque ele faz um barulho estranho.",
            "Vou levar na assistência quando sobrar um tempo."]},
        {"id": "ptN05", "kind": "narrative", "asks": [], "s": [
            "Ah, outra coisa, o Rui passou aqui no fim da tarde.",
            "A gente conversou sobre o jogo de domingo e sobre a viagem dele pro Porto.",
            "Ele volta só no mês que vem."]},
        {"id": "ptN06", "kind": "narrative", "asks": [], "s": [
            "Comecei a ouvir um podcast sobre história do Brasil no caminho pro trabalho.",
            "O episódio de hoje foi sobre a chegada da família real.",
            "É engraçado como o narrador fala rápido."]},
        {"id": "ptN07", "kind": "narrative", "asks": [], "s": [
            "Minha mãe ligou cedo contando do jardim dela.",
            "As roseiras finalmente floresceram depois de dois anos.",
            "Ela tá toda orgulhosa e mandou umas dez fotos."]},
        {"id": "ptN08", "kind": "narrative", "asks": [], "s": [
            "Voltando, o cachorro do vizinho latiu a noite inteira.",
            "Acordei umas três vezes e de manhã tava um zumbi.",
            "Parece que eles viajaram e deixaram o bicho sozinho."]},
        {"id": "ptE01", "kind": "errand", "asks": [0], "s": [
            "Ah, e manda um oi pro João da contabilidade.",
            "Faz tempo que a gente não se fala."]},
        {"id": "ptE02", "kind": "errand", "asks": [0], "s": [
            "Me lembra de responder o e-mail do contador até quinta.",
            "Ele pediu uns comprovantes de despesa.",
            "Não é nada urgente."]},
        {"id": "ptE03", "kind": "errand", "asks": [0], "s": [
            "Dá uma olhada se a assinatura do editor de vídeo renova esse mês.",
            "Eu nem uso mais aquele programa."]},
        {"id": "ptE04", "kind": "errand", "asks": [0], "s": [
            "Marca na minha agenda o dentista na terça às três.",
            "Eles ligaram confirmando hoje."]},
        {"id": "ptE05", "kind": "errand", "asks": [0], "s": [
            "Também troca a foto do meu perfil no site da empresa.",
            "Aquela de terno tá muito velha."]},
        {"id": "ptE06", "kind": "errand", "asks": [0], "s": [
            "Pesquisa pra mim um presente de aniversário pra minha irmã, coisa até cem reais.",
            "Ela gosta de livro e de planta."]},
        {"id": "ptE07", "kind": "errand", "asks": [0], "s": [
            "Outra coisa, renomeia aquela pasta de fotos do evento pra ficar com a data.",
            "Do jeito que tá eu nunca acho nada."]},
        {"id": "ptE08", "kind": "errand", "asks": [0], "s": [
            "Ah, confere se chegou o boleto da internet.",
            "Mês passado ele veio atrasado."]},
        {"id": "ptT01", "kind": "thinking", "asks": [], "s": [
            "Tô pensando se vale a pena trocar de operadora de celular.",
            "A minha cai toda vez que eu entro no elevador.",
            "Mas trocar dá um trabalho danado com a portabilidade."]},
        {"id": "ptT02", "kind": "thinking", "asks": [], "s": [
            "Fico na dúvida se faço o curso de inglês à noite ou de manhã.",
            "De manhã eu rendo mais, mas à noite sobra mais tempo.",
            "Sei lá, depois eu decido."]},
        {"id": "ptT03", "kind": "thinking", "asks": [], "s": [
            "Será que compensa comprar um carro elétrico agora?",
            "A gasolina tá cara, mas o carro elétrico ainda é caro também.",
            "Talvez espere mais um ano."]},
        {"id": "ptT04", "kind": "thinking", "asks": [], "s": [
            "Enfim, ando pensando em mudar o escritório pra perto do centro.",
            "O aluguel lá é mais alto, mas eu economizaria em deslocamento.",
            "Não sei, ainda tô fazendo as contas."]},
        {"id": "ptT05", "kind": "thinking", "asks": [], "s": [
            "Às vezes acho que eu trabalho demais no fim de semana.",
            "Meu médico falou pra eu descansar mais.",
            "Ele tem razão, mas é difícil desligar."]},
        {"id": "ptT06", "kind": "thinking", "asks": [], "s": [
            "Fiquei pensando naquele livro sobre hábitos que eu li ano passado.",
            "Ele dizia que o ambiente pesa mais que a força de vontade.",
            "Faz sentido, pelo menos comigo."]},
        {"id": "ptT07", "kind": "thinking", "asks": [], "s": [
            "Tô em dúvida se levo as crianças pra praia no feriado.",
            "Com chuva, a viagem vira um pesadelo.",
            "Vou olhar a previsão mais perto da data."]},
        {"id": "ptT08", "kind": "thinking", "asks": [], "s": [
            "Pensando alto aqui, talvez eu devesse delegar mais coisa.",
            "Eu fico segurando tarefa que outra pessoa faria melhor.",
            "É um hábito antigo meu."]},
        {"id": "ptA01", "kind": "aside", "asks": [], "s": [
            "Amor, desliga o forno aí pra mim.",
            "Valeu."]},
        {"id": "ptA02", "kind": "aside", "asks": [], "s": [
            "Pedro, abaixa um pouco a televisão, por favor.",
            "Tô gravando aqui."]},
        {"id": "ptA03", "kind": "aside", "asks": [], "s": [
            "Oi, Marta, já tô terminando.",
            "Me dá cinco minutinhos que eu desço."]},
        {"id": "ptA04", "kind": "aside", "asks": [], "s": [
            "Filho, guarda o tênis que tá no meio da sala.",
            "Alguém vai tropeçar nisso."]},
        {"id": "ptA05", "kind": "aside", "asks": [], "s": [
            "Pode deixar a encomenda aí na mesa, moço.",
            "Obrigado."]},
        {"id": "ptA06", "kind": "aside", "asks": [], "s": [
            "Mãe, eu te ligo depois, tô no meio de um negócio aqui.",
            "Beijo."]},
        {"id": "ptA07", "kind": "aside", "asks": [], "s": [
            "Ana, a reunião é às quatro, não às três.",
            "Isso, na sala de sempre."]},
        {"id": "ptA08", "kind": "aside", "asks": [], "s": [
            "Cadê o carregador que tava aqui?",
            "Ah, achei, tava embaixo do caderno."]},
    ],
    "en": [
        {"id": "enN01", "kind": "narrative", "asks": [], "s": [
            "Traffic was a mess this morning because of the rain.",
            "A twenty minute drive took almost an hour.",
            "At least I got a coffee before the first meeting."]},
        {"id": "enN02", "kind": "narrative", "asks": [], "s": [
            "We went to my nephew's birthday yesterday.",
            "He turned seven and got a blue bike.",
            "It was a small party at a hall near our place."]},
        {"id": "enN03", "kind": "narrative", "asks": [], "s": [
            "Anyway, the new gym near the office opened this week.",
            "I went at lunch and it was empty.",
            "The machines are new and the changing rooms are spotless."]},
        {"id": "enN04", "kind": "narrative", "asks": [], "s": [
            "My laptop has been running hot all week.",
            "I think it's dust in the fan, because it makes a strange noise.",
            "I'll take it to the repair shop when things calm down."]},
        {"id": "enN05", "kind": "narrative", "asks": [], "s": [
            "Oh, another thing, Rui came by late in the afternoon.",
            "We talked about Sunday's match and his trip to Porto.",
            "He's away until next month."]},
        {"id": "enN06", "kind": "narrative", "asks": [], "s": [
            "I started a history podcast for the drive to work.",
            "Today's episode was about the Tudors.",
            "The host talks really fast, which is funny."]},
        {"id": "enN07", "kind": "narrative", "asks": [], "s": [
            "My mum called early to tell me about her garden.",
            "The roses finally bloomed after two years.",
            "She's very proud and sent about ten photos."]},
        {"id": "enN08", "kind": "narrative", "asks": [], "s": [
            "Going back to it, the neighbour's dog barked all night.",
            "I woke up three times and felt like a zombie this morning.",
            "Apparently they went away and left the dog alone."]},
        {"id": "enE01", "kind": "errand", "asks": [0], "s": [
            "Oh, and say hi to John in accounts for me.",
            "We haven't spoken in ages."]},
        {"id": "enE02", "kind": "errand", "asks": [0], "s": [
            "Remind me to answer the accountant's email by Thursday.",
            "He asked for some expense receipts.",
            "It's nothing urgent."]},
        {"id": "enE03", "kind": "errand", "asks": [0], "s": [
            "Have a look at whether the video editor subscription renews this month.",
            "I don't even use that app anymore."]},
        {"id": "enE04", "kind": "errand", "asks": [0], "s": [
            "Put the dentist in my calendar for Tuesday at three.",
            "They called to confirm today."]},
        {"id": "enE05", "kind": "errand", "asks": [0], "s": [
            "Also, change my profile photo on the company site.",
            "The one in the suit is really old."]},
        {"id": "enE06", "kind": "errand", "asks": [0], "s": [
            "Find me a birthday present for my sister, something under fifty pounds.",
            "She likes books and plants."]},
        {"id": "enE07", "kind": "errand", "asks": [0], "s": [
            "Another thing, rename that folder of event photos so it has the date.",
            "I can never find anything in there."]},
        {"id": "enE08", "kind": "errand", "asks": [0], "s": [
            "Oh, check whether the internet bill came in.",
            "Last month it arrived late."]},
        {"id": "enT01", "kind": "thinking", "asks": [], "s": [
            "I keep wondering whether to switch mobile carriers.",
            "Mine drops every time I get in the lift.",
            "But switching is such a hassle with the number transfer."]},
        {"id": "enT02", "kind": "thinking", "asks": [], "s": [
            "I can't decide between the evening and the morning Spanish class.",
            "I focus better in the morning, but evenings are freer.",
            "I'll decide later."]},
        {"id": "enT03", "kind": "thinking", "asks": [], "s": [
            "Is it worth buying an electric car right now?",
            "Petrol is expensive, but electric cars are still pricey too.",
            "Maybe I'll wait another year."]},
        {"id": "enT04", "kind": "thinking", "asks": [], "s": [
            "Anyway, I've been thinking about moving the office closer to the centre.",
            "Rent is higher there, but I'd save on commuting.",
            "I don't know, I'm still doing the maths."]},
        {"id": "enT05", "kind": "thinking", "asks": [], "s": [
            "Sometimes I think I work too much at weekends.",
            "My doctor told me to rest more.",
            "He's right, but it's hard to switch off."]},
        {"id": "enT06", "kind": "thinking", "asks": [], "s": [
            "I was thinking about that book on habits I read last year.",
            "It said your surroundings matter more than willpower.",
            "That rings true, at least for me."]},
        {"id": "enT07", "kind": "thinking", "asks": [], "s": [
            "Not sure whether to take the kids to the coast over the bank holiday.",
            "If it rains, the trip turns into a nightmare.",
            "I'll look at the forecast closer to the date."]},
        {"id": "enT08", "kind": "thinking", "asks": [], "s": [
            "Thinking out loud here, maybe I should delegate more.",
            "I hold on to tasks someone else would do better.",
            "It's an old habit of mine."]},
        {"id": "enA01", "kind": "aside", "asks": [], "s": [
            "Love, can you turn the oven off for me?",
            "Thanks."]},
        {"id": "enA02", "kind": "aside", "asks": [], "s": [
            "Pete, turn the TV down a bit, please.",
            "I'm recording."]},
        {"id": "enA03", "kind": "aside", "asks": [], "s": [
            "Hi Martha, I'm almost done.",
            "Give me five minutes and I'll come down."]},
        {"id": "enA04", "kind": "aside", "asks": [], "s": [
            "Mate, put your trainers away, they're in the middle of the room.",
            "Someone's going to trip."]},
        {"id": "enA05", "kind": "aside", "asks": [], "s": [
            "You can leave the parcel on the table, thanks.",
            "Cheers."]},
        {"id": "enA06", "kind": "aside", "asks": [], "s": [
            "Mum, I'll call you back, I'm in the middle of something.",
            "Love you."]},
        {"id": "enA07", "kind": "aside", "asks": [], "s": [
            "Anna, the meeting is at four, not three.",
            "Yes, the usual room."]},
        {"id": "enA08", "kind": "aside", "asks": [], "s": [
            "Where's the charger that was here?",
            "Oh, found it, it was under the notebook."]},
    ],
}  # fmt: skip

# --- dev-split phrasings ---------------------------------------------------------------------
# Each is a prefix: the ask (or the restatement body) follows it in the same sentence.
DEV_PHRASINGS: dict[str, dict[str, list[str]]] = {
    "marker": {
        "pt": ["O mais importante de tudo é isso aqui: ", "Presta atenção nessa, que é a principal: ",
               "Se for pra fazer uma coisa só hoje, que seja essa: ", "A prioridade número um é: ",
               "O que realmente importa é o seguinte: ", "Isso aqui é o que mais me preocupa: ",
               "Antes de qualquer outra coisa, ", "O foco principal agora: "],
        "en": ["The main thing is this: ", "Most important of all, ",
               "If you only do one thing today, ", "Top priority: ",
               "What really matters is this: ", "This is the one I care about most: ",
               "Before anything else, ", "The big one: "],
    },
    "restate": {
        "pt": ["Então, resumindo: ", "No fim das contas, ", "Recapitulando, ",
               "Pra fechar, o principal: ", "Resumindo tudo isso: ", "Voltando ao que importa, ",
               "Em resumo, ", "Deixando claro, "],
        "en": ["So, to sum up: ", "At the end of the day, ", "To recap, ", "Bottom line, ",
               "Long story short: ", "Coming back to what matters, ", "In short, ",
               "Just to be clear, "],
    },
}  # fmt: skip


# Words too common to mark a topic (function words, time words, filler verbs). A pool block that
# shares any other word stem (first five letters of a word of four or more) with a base is left
# out of that base's cases, so a topic comes back only where the generator puts it.
_COMMON_WORDS = """
você isso está como mais também tipo então esse essa aquele aquela aquilo assim coisa aqui
agora depois minha nada tudo quando onde porque pelo pela hoje ontem amanhã manhã tarde noite
semana semanas cedo antes sempre vezes toda todo todos dias tempo três quatro cinco vinte duas
umas quase ainda sobre outra outro dela dele eles elas achei acho pensar pensando pensei tava
estava ficar fique ficou mando manda mandar lembra lembrar lembrei gente pessoa pessoas parece
talvez chega chegar passa passar veio vinha ligou nisso alguém termina esqueci mudar
that this with what your should would which there they have about when where because will
just from some morning night week weeks month last every time first next three four five
twenty minutes hour hours before after another thing things more still right look over came
went took going back start started away down even into read anything nothing someone asked
found thanks thank please been take called almost sent never
"""
_COMMON = frozenset(_COMMON_WORDS.split())


def topic_stems(sentences: list[str]) -> set[str]:
    return {
        w[:5]
        for t in sentences
        for w in re.findall(r"[^\W\d_]+", t.lower())
        if len(w) >= 4 and w not in _COMMON
    }


def pool_for(base: dict[str, Any]) -> list[dict[str, Any]]:
    """The pool blocks of the base's language that share no topic stem with the base."""
    own = topic_stems([base["ask"], *base["support"], *base["recur"], base["restate"]])
    return [b for b in POOL[base["lang"]] if not own & topic_stems(b["s"])]


def _phrasings() -> dict[str, dict[str, dict[str, list[str]]]]:
    """``{split: {kind: {lang: [prefix, ...]}}}``; the test split reads Codex's file."""
    codex = json.loads(CODEX_PATH.read_text(encoding="utf-8"))["phrasings"]
    test = {
        kind: {lang: codex[f"{kind}_{lang}"] for lang in ("pt", "en")}
        for kind in ("marker", "restate")
    }
    return {"dev": DEV_PHRASINGS, "test": test}


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]


def _split(base_id: str) -> str:
    return "dev" if int(base_id[2:]) % 2 else "test"


def build_case(
    base: dict[str, Any], family: str, k: int, rng: random.Random, phrasings: dict[str, Any]
) -> dict[str, Any]:
    lang, split = base["lang"], _split(base["id"])
    blocks: list[dict[str, Any]] = [
        {
            "kind": b["kind"],
            "src": b["id"],
            "s": [
                {"text": t, "tag": "ask" if i in b["asks"] else ""} for i, t in enumerate(b["s"])
            ],
        }
        for b in rng.sample(pool_for(base), k)
    ]
    if family == "first":
        pos = 0
    elif family == "recurrence":
        pos = rng.randint(0, k - 2)  # at least two blocks follow the base
    else:
        pos = rng.randint(0, k)
    ask = base["ask"]
    phrasing: dict[str, Any] | None = None
    if family == "marker":
        options = phrasings[split]["marker"][lang]
        index = rng.randrange(len(options))
        ask = options[index] + _lower_first(ask)
        phrasing = {"kind": "marker", "set": split, "index": index}
    base_block = {
        "kind": "base",
        "src": base["id"],
        "s": [{"text": ask, "tag": "main"}]
        + [{"text": t, "tag": "support"} for t in base["support"]],
    }
    blocks.insert(pos, base_block)
    if family == "recurrence":
        n = min(rng.choice([2, 3]), k - pos)
        hosts = sorted(rng.sample(range(pos + 1, k + 1), n))
        mentions = sorted(rng.sample(range(len(base["recur"])), n))
        for host, m in zip(hosts, mentions, strict=True):
            blocks[host]["s"].append({"text": base["recur"][m], "tag": "recur"})
    if family == "restate":
        options = phrasings[split]["restate"][lang]
        index = rng.randrange(len(options))
        blocks.append(
            {
                "kind": "restate",
                "src": base["id"],
                "s": [{"text": options[index] + base["restate"], "tag": "main"}],
            }
        )
        phrasing = {"kind": "restate", "set": split, "index": index}

    text, cursor = "", 0
    gold: dict[str, list[list[int]]] = {"main": [], "support": [], "recur": [], "errand": []}
    block_spans, sentences = [], []
    for block in blocks:
        start = None
        for sent in block["s"]:
            if text:
                text += " "
                cursor += 1
            s, e = cursor, cursor + len(sent["text"])
            text += sent["text"]
            cursor = e
            sentences.append([s, e])
            start = s if start is None else start
            key = {"main": "main", "support": "support", "recur": "recur", "ask": "errand"}
            if sent["tag"]:
                gold[key[sent["tag"]]].append([s, e])
        block_spans.append({"kind": block["kind"], "src": block["src"], "span": [start, cursor]})
    return {
        "id": f"{base['id']}-{family}-k{k}",
        "base": base["id"],
        "lang": lang,
        "split": split,
        "family": family,
        "k": k,
        "position": pos,
        "phrasing": phrasing,
        "text": text,
        "main": gold["main"],
        "support": gold["support"],
        "recur": gold["recur"],
        "asks": [gold["main"]] + [[span] for span in gold["errand"]],
        "blocks": block_spans,
        "sentences": sentences,
    }


def generate() -> dict[str, Any]:
    rng = random.Random(SEED)
    phrasings = _phrasings()
    cases = [
        build_case(base, family, k, rng, phrasings)
        for base in BASES
        for family in FAMILIES
        for k in LENGTHS
    ]
    return {"version": VERSION, "seed": SEED, "cases": cases}


def dump(data: dict[str, Any]) -> str:
    """The cases file: one case per line, so a diff names the cases it changes."""
    rows = ",\n".join(json.dumps(c, ensure_ascii=False) for c in data["cases"])
    head = f'{{"version": "{data["version"]}", "seed": {data["seed"]}, "cases": [\n'
    return head + rows + "\n]}\n"


def _summary(cases: list[dict[str, Any]]) -> list[str]:
    lines = []
    for k in LENGTHS:
        words = [len(c["text"].split()) for c in cases if c["k"] == k]
        lines.append(f"k={k}: {len(words)} cases, {min(words)} to {max(words)} words")
    return lines


def cmd_generate(_: argparse.Namespace) -> int:
    data = dump(generate())
    CASES_PATH.write_text(data, encoding="utf-8")
    cases = json.loads(data)["cases"]
    print(
        f"{CASES_PATH.name}: {len(cases)} cases, sha256 {hashlib.sha256(data.encode()).hexdigest()}"
    )
    print("\n".join(_summary(cases)))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(required=True)
    sub.add_parser("generate").set_defaults(func=cmd_generate)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
