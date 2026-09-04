# Preparação do CoppeliaSim

1. Abra o CoppeliaSim e crie uma cena nova.
2. Adicione um `Dummy` e defina seu alias como `DroneTarget`.
3. Adicione o modelo de quadricóptero e faça o script controlador dele seguir o dummy `/DroneTarget`. Para um primeiro teste cinemático, o próprio modelo ou dummy pode receber esse alias.
4. Mantenha habilitado o add-on ZeroMQ Remote API, normalmente iniciado automaticamente na porta `23000`.
5. Gere `output/waypoints_coppeliasim.csv` executando a missão de cobertura.
6. Valide o arquivo sem conectar:

   `python -m src.coppeliasim --dry-run`

7. Com a cena aberta e a simulação parada, execute:

   `python -m src.coppeliasim --object /target --scale 0.01 --speed 0.05 --warmup-s 3`

O valor `0.01` converte 1 metro real em 1 centímetro/unidade visual da cena. O terreno importado no CoppeliaSim deve usar exatamente a mesma escala. O programa primeiro mantém o alvo parado para o drone estabilizar e depois o leva progressivamente ao primeiro waypoint. A simulação é sincronizada e sempre encerrada mesmo se ocorrer uma falha durante o voo.
